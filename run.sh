#!/usr/bin/env bash
# Quick start — skips onboarding, uses existing .env

echo "🦞 Starting CodeClaw..."
exec "$(dirname "$0")/codeclaw" run
