---
title: Deployment
description: Deploy NOVA AI in production environments
---

# Deployment

NOVA AI supports multiple deployment strategies for different environments
and scales.

## Docker

The recommended way to deploy NOVA AI in production. Multi-stage builds
with CPU and GPU (NVIDIA CUDA, AMD ROCm) variants.

[:octicons-arrow-right-24: Docker deployment](docker.md)

## systemd (Linux)

Run NOVA AI as a managed system service on Linux servers.

[:octicons-arrow-right-24: systemd setup](systemd.md)

## launchd (macOS)

Register NOVA AI as a launch agent on macOS.

[:octicons-arrow-right-24: launchd setup](launchd.md)

## API Server

Run NOVA AI as an OpenAI-compatible HTTP server via `nova serve`.

[:octicons-arrow-right-24: API server guide](api-server.md)
