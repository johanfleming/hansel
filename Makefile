.PHONY: run auto watch install test help status config build publish publish-test clean

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
	@echo ""
	@echo "PyPI Publishing:"
	@echo "  make build        Build package for PyPI"
	@echo "  make publish-test Upload to TestPyPI"
	@echo "  make publish      Upload to PyPI (production)"
	@echo "  make clean        Clean build artifacts"

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

# PyPI publishing
clean:
	rm -rf dist/ build/ *.egg-info/

build: clean
	python3 -m pip install --upgrade build
	python3 -m build

publish-test: build
	python3 -m pip install --upgrade twine
	python3 -m twine upload --repository testpypi dist/*

publish: build
	python3 -m pip install --upgrade twine
	python3 -m twine upload dist/*
