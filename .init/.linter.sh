#!/bin/bash
cd /home/kavia/workspace/code-generation/laundry-payment-system-242166-242181/laundry_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

