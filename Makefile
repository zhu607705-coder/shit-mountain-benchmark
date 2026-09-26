.PHONY: test arena baselines legacy-baselines extreme-full preview package
arena:
	python3 scripts/launch_arena.py
test:
	python3 scripts/check.py
baselines:
	python3 scripts/extreme.py --task all --scale smoke --output reports/extreme-baselines
legacy-baselines:
	python3 run_baselines.py
extreme-full:
	python3 scripts/extreme.py --task all --scale full --timeout 900 --output reports/extreme-full
preview:
	python3 -m http.server 8769 --bind 127.0.0.1
package:
	python3 organizer/package_release.py
	python3 organizer/export_contestants.py --profile extreme --scale full
