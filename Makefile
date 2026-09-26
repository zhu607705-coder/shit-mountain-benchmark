.PHONY: test baselines preview package
test:
	python3 scripts/check.py
baselines:
	python3 run_baselines.py
preview:
	python3 -m http.server 8769 --bind 127.0.0.1
package:
	python3 organizer/package_release.py
