#!/bin/sh
# Fetches 122-day tx histories (RPC tx_search) for the universe pools without one, 3 at a time,
# each starting on a different RPC node. Usage: sh fetch_missing.sh missing_pairs.txt
i=0
while read p; do
  python3 fetch_pool_history_rpc.py "$p" 30536384 122 "hist_rpc/$p.json" $((i % 3)) > "hist_rpc/$p.log" 2>&1 &
  i=$((i+1))
  if [ $((i % 3)) -eq 0 ]; then wait; fi
done < "$1"
wait
echo all done
