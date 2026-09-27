# Thin entry points. Run inside Linux (WSL2 Ubuntu 24.04 or the Docker image).
# Build output lives outside the repo (default ~/build/hfdns) so it never lands
# in the OneDrive-synced working copy.

BUILD_DIR  ?= $(HOME)/build/hfdns
BUILD_TYPE ?= RelWithDebInfo
VENV       ?= $(HOME)/venvs/hfdns
CONFIG     ?= config/dev.yaml

# Pinned: clang-tidy 18 cannot see std::expected in GCC 13's libstdc++.
CLANG_FORMAT   ?= clang-format-19
RUN_CLANG_TIDY ?= run-clang-tidy-19
JOBS           ?= $(shell nproc)

PY         := $(VENV)/bin/python
LB         := $(BUILD_DIR)/core/hfdns-lb
CXX_FILES  := $(shell find core -name '*.cpp' -o -name '*.hpp')
CXX_SRCS   := $(filter %.cpp,$(CXX_FILES))
PY_PATHS   := tests

.PHONY: help venv configure build test test-cpp test-py format lint lint-cpp lint-py \
        check-config run-dev clean

help:
	@echo "targets: venv configure build test format lint check-config run-dev clean"
	@echo "vars:    BUILD_DIR=$(BUILD_DIR) BUILD_TYPE=$(BUILD_TYPE) VENV=$(VENV) CONFIG=$(CONFIG)"

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev]"

configure:
	cmake -S . -B $(BUILD_DIR) -G Ninja -DCMAKE_BUILD_TYPE=$(BUILD_TYPE)

build: configure
	cmake --build $(BUILD_DIR)

test: test-cpp test-py

test-cpp: build
	ctest --test-dir $(BUILD_DIR) --output-on-failure --timeout 30

test-py: build
	HFDNS_BUILD_DIR=$(BUILD_DIR) $(PY) -m pytest

format:
	$(CLANG_FORMAT) -i $(CXX_FILES)
	$(PY) -m ruff format $(PY_PATHS)
	$(PY) -m ruff check --fix $(PY_PATHS)

lint: lint-cpp lint-py

lint-cpp: configure
	$(CLANG_FORMAT) --dry-run --Werror $(CXX_FILES)
	$(RUN_CLANG_TIDY) -p $(BUILD_DIR) -quiet -j $(JOBS) $(abspath $(CXX_SRCS))

lint-py:
	$(PY) -m ruff format --check $(PY_PATHS)
	$(PY) -m ruff check $(PY_PATHS)

check-config: build
	$(LB) --check-config --config $(CONFIG)

run-dev: build
	$(LB) --config $(CONFIG)

clean:
	rm -rf $(BUILD_DIR)
