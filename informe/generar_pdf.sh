#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

cd "$(dirname "$0")"
latexmk -pdf main.tex
