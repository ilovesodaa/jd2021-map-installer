#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m jd2021_installer.main "$@"
