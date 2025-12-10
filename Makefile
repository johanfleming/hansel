.PHONY: run auto watch install test help status config

# Default target
help:
	@echo "Hansel - Autonomous Terminal AI Bridge"
	@echo ""
	@echo "Usage:"
	@echo "  make run          Run hansel help"
	@echo "  make auto         Run hansel auto claude"
	@echo "  make watch        Run hansel watch claude"
	@echo "  make status       Show hansel status"
	@echo "  make config       Configure hansel"
	@echo "  make install      Install hansel to ~/.local/bin"
	@echo "  make test         Run tests"

run:
	python3 hansel.py help

auto:
	python3 hansel.py auto claude

watch:
	python3 hansel.py watch claude

status:
	python3 hansel.py status

config:
	python3 hansel.py config

install:
	python3 install.py

test:
	python3 test_hansel.py
