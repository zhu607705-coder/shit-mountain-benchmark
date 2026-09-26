#!/usr/bin/env python3
"""Observable streaming latency/token recorder. It never infers hidden thinking time."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import random
import statistics
import time
from urllib import error, parse, request

from cli import MAX_FILE, load_config, read_json, validate_config


def percentile(values, fraction):
    if not values: return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stats(values):
    clean = [x for x in values if x is not None and type(x) in (int, float) and math.isfinite(x)]
    return {"observations": len(clean), "missing": len(values) - len(clean),
            "mean": statistics.fmean(clean) if clean else None, "max": max(clean) if clean else None,
            "min": min(clean) if clean else None, "p50": percentile(clean, .5), "p95": percentile(clean, .95),
            "sum": sum(clean) if clean else None}


def count_or_none(value):
    return value if type(value) is int and value >= 0 else None


def response_chunks(response, deadline):
    """Read available bytes, not unbounded lines; progress cannot reset the absolute deadline."""
    total = 0
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0: raise TimeoutError()
        raw = getattr(getattr(response, 'fp', None), 'raw', None)
        connection = getattr(raw, '_sock', None)
        if connection is not None: connection.settimeout(remaining)
        chunk = response.read1(4096)
        if not chunk: return
        total += len(chunk)
        if total > MAX_FILE: raise ValueError('response_size_limit')
        yield chunk


def sse_payloads(response, deadline):
    buffer, event_lines = b'', []
    for chunk in response_chunks(response, deadline):
        buffer += chunk
        while b'\n' in buffer:
            raw, buffer = buffer.split(b'\n', 1)
            line = raw.decode('utf-8').rstrip('\r')
            if line.startswith('data:'): event_lines.append(line[5:].lstrip())
            elif not line and event_lines:
                yield '\n'.join(event_lines)
                event_lines = []
    if buffer or event_lines: raise ValueError('unterminated_sse_event')


class Observation:
    def __init__(self, started):
        self.started = started
        self.first_event = self.first_answer = self.first_reasoning = self.last_reasoning = None
        self.answer_times, self.answer = [], []
        self.reasoning_chars = self.reasoning_events = 0
        self.usage, self.finish, self.model = None, None, None
        self.events = 0
        self.done = False

    def event(self, payload, at):
        if not isinstance(payload, dict) or not isinstance(payload.get('choices', []), list):
            raise ValueError('malformed_stream_event')
        self.events += 1
        if self.first_event is None: self.first_event = at
        if isinstance(payload.get("usage"), dict): self.usage = payload["usage"]
        if isinstance(payload.get("model"), str): self.model = payload["model"]
        for choice in payload.get("choices", []):
            if not isinstance(choice, dict): raise ValueError('malformed_stream_choice')
            if choice.get("index", 0) != 0: continue
            if choice.get("finish_reason") is not None: self.finish = choice["finish_reason"]
            delta = choice.get("delta", choice.get("message", {})) or {}
            if not isinstance(delta, dict): raise ValueError('malformed_stream_delta')
            answer = delta.get("content")
            if isinstance(answer, str) and answer:
                if self.first_answer is None: self.first_answer = at
                self.answer_times.append(at); self.answer.append(answer)
            # Some compatible providers expose a reasoning stream. Only count it; never save its text.
            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning, str) and reasoning:
                if self.first_reasoning is None: self.first_reasoning = at
                self.last_reasoning = at
                self.reasoning_events += 1; self.reasoning_chars += len(reasoning)

    def result(self, ended, *, streamed):
        usage = self.usage or {}
        details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
        if not isinstance(details, dict): details = {}
        total = count_or_none(usage.get("completion_tokens", usage.get("output_tokens")))
        reasoning = count_or_none(details.get("reasoning_tokens"))
        prompt = count_or_none(usage.get("prompt_tokens", usage.get("input_tokens")))
        input_details = usage.get('prompt_tokens_details') or usage.get('input_tokens_details') or {}
        cached = count_or_none(input_details.get('cached_tokens')) if isinstance(input_details, dict) else None
        text = ''.join(self.answer)
        ms = lambda at: None if at is None else (at - self.started) * 1000
        gaps = [(b - a) * 1000 for a, b in zip(self.answer_times, self.answer_times[1:])]
        elapsed = max(0, ended - self.started)
        return {"total_ms": elapsed * 1000,
                "first_event_ms": ms(self.first_event) if streamed else None,
                "ttft_ms": ms(self.first_answer) if streamed else None,
                "first_reasoning_delta_ms": ms(self.first_reasoning) if streamed else None,
                "observed_reasoning_stream_span_ms": ((self.last_reasoning - self.first_reasoning) * 1000 if streamed and self.reasoning_events > 1 else None),
                "thinking_time_ms": None,
                "thinking_time_source": "not observable from this transport; TTFT is not internal thinking time",
                "input_tokens": prompt, "cached_input_tokens": cached, "output_tokens": total, "reasoning_tokens": reasoning,
                "output_token_scope": "provider-reported generated total; may include reasoning and invisible formatting",
                "visible_output_tokens": None, "visible_output_chars": len(text), "visible_output_bytes": len(text.encode()),
                "non_reasoning_generated_tokens": total - reasoning if total is not None and reasoning is not None and total >= reasoning else None,
                "reasoning_stream_chars": self.reasoning_chars, "reasoning_stream_events": self.reasoning_events,
                "answer_chunk_count": len(self.answer_times), "answer_chunk_gap_ms": stats(gaps),
                "provider_output_tokens_per_second": total / elapsed if total is not None and elapsed > 0 else None,
                "amortized_ms_per_provider_output_token": elapsed * 1000 / total if total else None,
                "usage_reported": self.usage is not None, "finish_reason": self.finish, "streamed": streamed,
                "stream_done_marker": self.done, "model_reported": self.model, "response_text": text}


def stream_call(config, messages, *, reasoning_effort=None, token_limit_field="max_tokens"):
    config = validate_config(config)
    secret = os.environ.get(config["api_key_env"])
    if not secret: raise ValueError("missing API key environment variable: " + config["api_key_env"])
    if token_limit_field not in ("max_tokens", "max_completion_tokens"): raise ValueError("unsupported token-limit field")
    payload = {"model": config["model"], "messages": messages, "temperature": config["temperature"],
               token_limit_field: config["max_tokens"], "stream": True, "stream_options": {"include_usage": True}}
    if reasoning_effort: payload["reasoning_effort"] = reasoning_effort
    endpoint = config["base_url"].rstrip('/') + '/chat/completions'
    req = request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(),
                          headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": "Bearer " + secret})
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, *args): return None
    handlers = [NoRedirect()]
    if parse.urlsplit(endpoint).hostname in ('localhost', '127.0.0.1', '::1'): handlers.insert(0, request.ProxyHandler({}))
    started = time.perf_counter()
    observation = Observation(started)
    streamed, status, error_code, header_ms, request_id = False, "error", None, None, None
    try:
        with request.build_opener(*handlers).open(req, timeout=config["timeout"]) as response:
            header_ms = (time.perf_counter() - started) * 1000
            request_id = response.headers.get('x-request-id') or response.headers.get('request-id')
            streamed = 'text/event-stream' in response.headers.get('Content-Type', '')
            if not streamed:
                body = b''.join(response_chunks(response, started + config['timeout']))
                if secret.encode() in body: raise ValueError("credential_echo_refused")
                decoded = read_json(body.decode())
                if secret in json.dumps(decoded, ensure_ascii=False): raise ValueError("credential_echo_refused")
                observation.event(decoded, time.perf_counter())
            else:
                for data in sse_payloads(response, started + config['timeout']):
                    if data == '[DONE]': observation.done = True; break
                    decoded = read_json(data)
                    if secret in json.dumps(decoded, ensure_ascii=False): raise ValueError("credential_echo_refused")
                    if 'error' in decoded: raise ValueError("provider_stream_error")
                    observation.event(decoded, time.perf_counter())
            status = "completed" if observation.finish == 'stop' and (not streamed or observation.done) else "incomplete"
    except error.HTTPError as exc:
        error_code = 'http_' + str(exc.code)
    except (TimeoutError,):
        status, error_code = "timeout", "request_timeout"
    except error.URLError as exc:
        status, error_code = ("timeout", "request_timeout") if isinstance(exc.reason, TimeoutError) else ("error", "connection_error")
    except http.client.HTTPException:
        status, error_code = "incomplete", "incomplete_http_response"
    except (ValueError, UnicodeDecodeError, KeyError, IndexError, TypeError, OSError) as exc:
        error_code = str(exc) if str(exc) in {"response_size_limit", "credential_echo_refused", "provider_stream_error", "unterminated_sse_event"} else "protocol_or_io_error"
    ended = time.perf_counter()
    result = observation.result(ended, streamed=streamed)
    if error_code == 'credential_echo_refused': result['response_text'] = ''
    result.update(status=status, error_code=error_code, response_headers_ms=header_ms,
                  requested_reasoning_effort=reasoning_effort, token_limit_field=token_limit_field, request_id=request_id)
    # No raw usage object or reasoning stream is persisted; only defined metadata is retained.
    if secret in json.dumps(result, ensure_ascii=False):
        result.update(status='error', error_code='credential_echo_refused', response_text='', model_reported=None)
        def redact(value):
            if isinstance(value, str): return value.replace(secret, '[REDACTED]')
            if isinstance(value, dict): return {k: redact(v) for k, v in value.items()}
            if isinstance(value, list): return [redact(v) for v in value]
            return value
        result = redact(result)
    return result


def validate_plan(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('prompts'), list) or not plan['prompts']:
        raise ValueError("plan requires a nonempty prompts list")
    ids = set()
    for prompt in plan['prompts']:
        pid = prompt.get('id')
        if not isinstance(pid, str) or not pid or pid in ids: raise ValueError("unique prompt ids required")
        ids.add(pid)
        messages = prompt.get('messages')
        if not isinstance(messages, list) or not messages: raise ValueError("messages required")
        for message in messages:
            if message.get('role') not in ('system', 'developer', 'user', 'assistant') or not isinstance(message.get('content'), str):
                raise ValueError("only text conversation messages are supported")
    return plan


METRICS = ('total_ms', 'ttft_ms', 'first_event_ms', 'first_reasoning_delta_ms', 'observed_reasoning_stream_span_ms',
           'output_tokens', 'input_tokens', 'cached_input_tokens', 'reasoning_tokens',
           'visible_output_chars', 'thinking_time_ms', 'provider_output_tokens_per_second')


def summarize(records):
    measured = [r for r in records if not r['warmup']]
    def group(rows):
        successful = [r for r in rows if r['status'] == 'completed']
        logical = [r for r in rows if r.get('logical_final')]
        return {'attempts': len(rows), 'successful_attempts': len(successful), 'failed_attempts': len(rows) - len(successful),
                'logical_runs': len(logical), 'failed_logical_runs': sum(r['status'] != 'completed' for r in logical),
                'all_attempt_metrics': {key: stats([r.get(key) for r in rows]) for key in METRICS},
                'successful_attempt_metrics': {key: stats([r.get(key) for r in successful]) for key in METRICS},
                'logical_total_ms': stats([r['logical_total_ms'] for r in logical]),
                'logical_ttft_ms': stats([r.get('logical_ttft_ms') for r in logical])}
    return {'overall': group(measured), 'by_prompt': {pid: group([r for r in measured if r['prompt_id'] == pid]) for pid in sorted({r['prompt_id'] for r in measured})},
            'warmup_attempts_excluded': sum(r['warmup'] for r in records),
            'interpretation': 'Quantiles are descriptive across recorded attempts, not confidence intervals. Missing usage or thinking times are null, never zero. Failures remain in all-attempt and logical-run summaries.'}


def run_plan(config, plan, output, *, rounds=3, warmups=0, retries=0, seed=1, conversation=False,
             reasoning_effort=None, token_limit_field="max_tokens", simulated=False, caller=stream_call):
    config, plan = validate_config(config), validate_plan(plan)
    if type(rounds) is not int or rounds < 1 or warmups < 0 or retries < 0 or retries > 3: raise ValueError("invalid repetition counts")
    output = Path(output)
    if output.exists(): raise ValueError("output directory already exists; use a new run id")
    output.mkdir(parents=True)
    records, rng = [], random.Random(seed)
    jsonl = output / 'attempts.jsonl'
    for round_number in range(-warmups, rounds):
        prompts = list(plan['prompts'])
        if not conversation: rng.shuffle(prompts)
        history = []
        for prompt in prompts:
            messages = history + prompt['messages'] if conversation else prompt['messages']
            logical_started = time.perf_counter()
            logical_first_answer = None
            logical_outputs, logical_reasoning = [], []
            for attempt in range(retries + 1):
                attempt_started = time.perf_counter()
                result = caller(config, messages, reasoning_effort=reasoning_effort, token_limit_field=token_limit_field)
                if result.get('ttft_ms') is not None and logical_first_answer is None:
                    logical_first_answer = (attempt_started - logical_started) * 1000 + result['ttft_ms']
                logical_outputs.append(result.get('output_tokens'))
                logical_reasoning.append(result.get('reasoning_tokens'))
                result.update(prompt_id=prompt['id'], round=round_number + 1, attempt=attempt + 1, warmup=round_number < 0,
                              alias=config['alias'], model_requested=config['model'], simulated=simulated,
                              prompt_sha256=hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                              logical_final=result['status'] == 'completed' or attempt == retries,
                              logical_total_ms=(time.perf_counter() - logical_started) * 1000,
                              logical_ttft_ms=logical_first_answer,
                              logical_output_tokens=sum(logical_outputs) if all(v is not None for v in logical_outputs) else None,
                              logical_reasoning_tokens=sum(logical_reasoning) if all(v is not None for v in logical_reasoning) else None,
                              output_tokens_known_lower_bound=sum(v for v in logical_outputs if v is not None),
                              source='host', measurement_source='host_api_stream', measurement_scope='logical_api_run',
                              latency_source='monotonic_host_clock')
                records.append(result)
                with jsonl.open('a', encoding='utf-8') as stream: stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')
                if result['status'] == 'completed': break
            if conversation and result['status'] == 'completed': history = messages + [{'role': 'assistant', 'content': result['response_text']}]
            elif conversation:
                # Subsequent turns would have a different causal context, so do not silently continue.
                break
    summary = summarize(records)
    summary.update(schema_version='0.2.0', recorded_at=datetime.now(timezone.utc).isoformat(), simulated=simulated,
                   config=config, rounds=rounds, warmups=warmups, retries=retries, order_seed=seed, conversation=conversation,
                   transport='chat-completions-sse', reasoning_effort=reasoning_effort,
                   plan_sha256=hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                   planned_measured_logical_runs=rounds * len(plan['prompts']),
                   not_executed_logical_runs=rounds * len(plan['prompts']) - summary['overall']['logical_runs'])
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    fields = ['prompt_id', 'round', 'attempt', 'alias', 'model_requested', 'simulated', 'measurement_source', 'request_id',
              'warmup', 'status', 'error_code', *METRICS,
              'visible_output_tokens', 'output_token_scope', 'logical_final', 'logical_total_ms', 'logical_ttft_ms',
              'logical_output_tokens', 'logical_reasoning_tokens', 'finish_reason', 'streamed']
    with (output / 'attempts.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n'); writer.writeheader(); writer.writerows(records)
    with (output / 'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['scope','population','metric','observations','missing','mean','max','min','p50','p95','sum'], lineterminator='\n')
        writer.writeheader()
        for scope, group in [('overall', summary['overall']), *summary['by_prompt'].items()]:
            for population in ('all_attempt_metrics', 'successful_attempt_metrics'):
                for metric, values in group[population].items(): writer.writerow({'scope':scope,'population':population,'metric':metric,**values})
            for metric in ('logical_total_ms', 'logical_ttft_ms'):
                writer.writerow({'scope':scope,'population':'logical_runs','metric':metric,**group[metric]})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--prompts', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--warmups', type=int, default=0)
    parser.add_argument('--retries', type=int, default=0)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--conversation', action='store_true')
    parser.add_argument('--reasoning-effort')
    parser.add_argument('--token-limit-field', choices=('max_tokens', 'max_completion_tokens'), default='max_tokens')
    args = parser.parse_args()
    summary = run_plan(load_config(args.config), read_json(Path(args.prompts).read_text()), args.output,
                       rounds=args.rounds, warmups=args.warmups, retries=args.retries, seed=args.seed,
                       conversation=args.conversation, reasoning_effort=args.reasoning_effort, token_limit_field=args.token_limit_field)
    print(json.dumps({'output': args.output, 'overall': summary['overall'], 'simulated': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
