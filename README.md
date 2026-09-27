# Terra Classic LP returns vs. holding

An open, reproducible measurement of how liquidity providers (LPs) on Terra Classic DEXes did compared
with simply holding the same two tokens. Everything here is computed from on-chain data. The code,
the data and the method are public so that anyone can check the results, rerun them on other pools or
other dates, and tell us where we are wrong.

**Read the report:** https://pabloabritos.github.io/terra-classic-lp-research/ (the same page is in [`docs/index.html`](docs/index.html); it is built from `report/template.html` by `report/build.py`, which also writes `report/index.html`, the version used for the Claude artifact). This README explains how to reproduce it. If you are an AI agent, or about to hand this to one, see [`AGENTS.md`](AGENTS.md); the report also has suggested prompts.

## The question

Over a given period, did one LP share end up worth more or less than the tokens it held at the start,
if you had just kept those tokens?

    LP vs HODL = value(tokens one LP share holds at the end) / value(tokens it held at the start) - 1

Both baskets are valued at the **end** price, so a falling token price does not count against the pool.
Only what the pool itself did counts. Measuring per LP share means other people's deposits and
withdrawals do not affect the result. External rewards (farming, incentives) are not included.

## What is covered

- **Snapshot (end of every window):** block `30536384`, 2026-09-24 02:05:40 UTC.
- **Start dates:** every day from 1 to 139 days before the snapshot (`analysis/heights.json`).
- **Pools:** every pool of five DEX factories with at least $2,000 of liquidity at the snapshot
  (`analysis/universe.json`):

  | DEX | Factory |
  |---|---|
  | Terraswap | `terra1jkndu9w5attpz09ut02sgey5dd3e8sq5watzm0` |
  | Terraport V2 | `terra1n75fgfc8clsssrm2k0fswgtzsvstdaah7la6sfu96szdu22xta0q57rqqr` |
  | Terraport V3 | `terra1y55punu6m5cm8sgqdgt6ngevtyklaylc09qxputn6ksye4ptf9ysxmtyl6` |
  | luncswap | `terra154r5ft4dktg9kt9r980zw4ywry6krh9ncevu0ya54p6j50kncptsm8sdup` |
  | Garuda DeFi | `terra1ypwj6sw25g0qcykv7mzmcvsndvx56r3yrgkaw3fds7yzwl7fwwcsnxkeh7` |

Not covered yet: CL8Y DEX, pools under $2,000, and anything before May 2026. See "Contributing".

## How the numbers are produced

All scripts are in [`analysis/`](analysis/), plain Python 3 with no dependencies. Run them from that
folder. Every answer from the chain is cached in `analysis/archive_cache.json`, so the whole pipeline
runs offline in seconds; delete the cache (or set `ARCHIVE_RPC`) to re-query a node yourself.

| Step | Script | Output |
|---|---|---|
| Block height for each daily start date | `heights.py` | `heights.json` |
| Pool universe at the snapshot (all five factories, USD value, pair type) | `universe.py` | `universe.json` |
| Token symbols | `labels.py` | `labels.json` |
| Pool state at every start height, mid price of concentrated pools | `fetch_states.py` | `archive_cache.json` |
| **LP vs HODL for every pool and start date**, split into fees and divergence loss | `compute.py` | `results.json` |
| Swap-by-swap tx histories, 122 days (for volume, fees and the independent rewind) | `fetch_pool_history_rpc.py`, `fetch_missing.sh` | `hist_rpc/*.json` |
| Fees actually paid by traders and kept by LPs, from each tx's token movements | `fees_observed.py` | printed |
| Volatility, volume and the σ²/8 break-even test | `lvr_check.py 120` | `lvr_120.json`, `lvr_120_excluded.json` |
| Governance-funded LUNC/USDC pools: DAO proposals and position | `dao_fetch.py`, `dao_position.py` | `dao_*.json` |

### Two independent ways to the same number

1. **Archive state** (`compute.py`): reads each pool's reserves and LP share supply directly from an
   archive node at the start and end heights. Default node: Stakely's public RPC
   (`https://terraclassic-rpc-server-01.stakely.io`), which as of September 2026 serves contract state
   back to about height 28.5M.
2. **Rewind** (`rewind.py`): starts from the state at the snapshot and undoes every transaction that
   touched the pool, using the actual token movements it produced, with no fee formula assumed.
   `debug_rewind.py` checks the rewound state block by block against the real state, and
   `check_counts.py` recounts each day's transactions on a second node.

For the 54 values checked both ways (pools with a rewind history, at 30/60/90/120 days) they agree to within 0.005 percentage points. `lvr_check.py` only uses pools whose rewind lands on the real archive state at the start of the window, to one part in a million, and lists the ones it leaves out.

### Things we learned about the data sources

- The Hexxagon LCD's transaction search silently returns nothing for transactions older than about
  10 days. The RPC `tx_search` of Hashed (`67.213.123.159:26657`), FRG (`135.181.79.188:26657`), ov
  (`131.153.242.219:26657`) and Stakely agree with each other and are complete.
- Most public LCD and RPC endpoints keep contract state for about 10 days only. Stakely's RPC keeps
  it much longer (see above).
- The Garuda factory returns pairs 20 at a time with its own pagination format
  (`{"pairs":{"pagination":{"limit":20,"start_after":[asset1, asset2]}}}`); without it you only see the
  first 10 of its 254 pairs.

## Contributing

This is meant to be extended and challenged. Useful contributions:

- **Run it on other pools, DEXes or periods** and share the results, whether they confirm or contradict
  ours. CL8Y DEX is the most obvious gap.
- **Historical data.** Public nodes forget old state quickly. Tx histories and state snapshots from
  archive nodes, especially from before May 2026, would let the analysis go further back.
- **Fixes.** If a script is wrong, or a number in the report does not match what you get, open an issue
  with the command you ran and its output.

## License

Code: MIT (`LICENSE`). Data and report: CC BY 4.0 (`LICENSE-DATA.md`).
