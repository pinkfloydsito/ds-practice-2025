#!/bin/bash

for node in {1..3}; do
  echo "Checking db-node-$node..."
  docker compose exec -it db-node$node curl -s localhost:50052/health
  echo ""
  echo "----------------------------------"
done
