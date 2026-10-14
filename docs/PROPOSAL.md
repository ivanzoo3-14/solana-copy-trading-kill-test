Kill Test - an open-source evaluation harness for Solana trading strategies

Applicant: Ivan Zamora-Solano (individual) | Greenville, SC, USA | ivanzoo12@gmail.com
Repository: https://github.com/ivanzoo3-14/solana-copy-trading-kill-test
Requested: $12,000 | 13 weeks, part-time | milestone-based


1. SUMMARY

Crypto strategy claims are unfalsifiable by default. They are scored on telemetry that does not measure edge, tested on windows chosen after the fact, and never published when they fail. I know because I built one: a Solana micro-cap copy-trading system, seven months of work, which I then stopped tuning and submitted to a rigorous test. It failed, I published the failure, and the instrument that killed it is the deliverable here.

Kill Test is that instrument: an open-source, pre-registration-enforcing evaluation harness for Solana trading strategies. It is already built and running. This proposal funds making it properly usable by others, hardening it against a defect register I have already written, and using it to publish two further pre-registered evaluations - whatever they find.


2. THE PROBLEM THIS ADDRESSES

A strategy claim normally reaches a reader as a chart, a backtest, and a number. Four things are usually missing, and each one is cheap to add and expensive to omit:

- A criterion frozen before the data. Without it, every parameter is a degree of freedom chosen with hindsight.
- Friction that is measured, not assumed. The standard mistake is comparing a venue's quote to that venue's own mid, which forces slippage toward zero by construction. I made that mistake, and then replaced it: depth-based impact across two notionals against an independent mid, which measures median 0.40% per side on Solana micro-caps.
- A ceiling, computed first. The perfect-exit bound shows the most any strategy on a signal set could leave on the table. If it does not clear friction, the strategy cannot work at any speed, and no amount of exit-rule engineering will save it.
- The negative results. The ecosystem's most reusable information is what does not work, and almost nobody publishes it.


3. WHAT ALREADY EXISTS

The harness runs today, paper-only, against live Solana data. It produced a complete negative result:

- Pre-registered verdict, median net at 5 minutes (n=357): -2.51%, 40.1% positive, one-way sign test p = 0.9999
- Take-profit / stop / timeout rules (60 coarse + 96 fine = 156 combinations): all negative; best -1.07%
- Perfect-exit ceiling, all horizons: +10.17% median (CI +7.27 to +13.89) - and a 900-second-plus phenomenon
- Perfect-exit ceiling, first 30-120 seconds: -0.78% net, +0.00% gross; age-clean 300-second reading -0.97%
- Entry timing (matched-holding control): median paired difference exactly 0
- Detection latency: 0.0 seconds / same-slot, derived from slot numbers rather than a drift-prone clock

Two findings would save another builder months. First, the median signal's best price in its first two minutes is its first observed price - in 62-72% of paths nothing later exceeds the first sample by even 0.5 percentage points. There is no fast pop to capture at any execution speed. Second, the upside that does exist lives in a fat right tail hours out, and every consistent exit rule truncates exactly that tail: adding a take-profit lifts the median and the win rate while collapsing the mean.

And the instrument is honest about itself. A 30-invariant audit of the raw data found 12 failing, each attributed. Four defects were found in the instrument after it had passed review: a guard silently deleting the deepest losses; bars labelled "30 seconds" fetched at a median age of 87 seconds, which flattered published figures; a friction number that did not reproduce; and a restart path that re-queued the entire history. All are documented, and the published numbers were re-derived and corrected rather than quietly overwritten.


4. WHY THIS IS A PUBLIC GOOD

- A reusable instrument, not a private edge. Anyone - builder, reviewer, investor - can point it at a strategy class and get a pre-registered, friction-honest answer.
- Measured constants others can reuse today: micro-cap friction at 0.40% per side; decay medians of -9.7% (1 hour), -62.5% (24 hours), -86.9% (7 days) against a +699% mean at 1 hour; runner frequency; and a no-information control showing entry timing after detection carries no measurable signal.
- A template for publishing negative results, including the corrections log - the part that makes the rest credible.
- Open source throughout. MIT licensed; the repository, the writeup, the frozen pre-registration and every probe that re-derives a published number are public already.


5. WHY SOLANA

The measurement is Solana-native, not a generic backtester pointed at a chain:

- Same-slot detection via logsSubscribe with per-wallet filters, with latency derived clock-independently from slot numbers (slot duration measured from block_time/slot pairs at 0.218-0.225 seconds - an assumed constant had been inflating every latency figure by 1.84x).
- Solana-specific cost structure: the Jupiter-versus-DEX price basis, and launchpad-era pool depths shallow enough that a $50 order moves the price - which is precisely why friction has to be measured with size rather than quoted.
- The findings bound Solana micro-cap behaviour and are not transferable elsewhere without re-measuring, which is the point of shipping the instrument rather than the conclusion.


6. DELIVERABLES AND MILESTONES

Part-time (~10 hours/week), 13 weeks, each milestone independently verifiable.

M1 - Open-source release (weeks 1-3). Repository already public; this funds making it properly usable: portable paths, one-command reproduction of the published v1 result, a README stating what the tool does not do, and the data dictionary. Acceptance: an outside reader reproduces the headline table.

M2 - Instrument hardening against the written defect register (weeks 3-6). Twelve audit invariants running in CI; horizon-age gating (a bar may only be scored if fetched within 1.2x its labelled horizon); admissibility changes must move the config fingerprint; bounded restart re-queue; versioned glitch policy recorded in every affected record. Acceptance: invariants green on the frozen dataset, defect register published with each item closed.

M3 - Two further pre-registered evaluations (weeks 6-11). (i) The wallet-selection holdout already collecting, published when its registered window closes. (ii) One further strategy class measured with the same instrument. Acceptance: both verdict documents published regardless of sign, each with its frozen criterion and its own data-quality audit.

M4 - Documentation, dataset release, final report (weeks 11-13). Acceptance: an outside reader reproduces the headline numbers from the released data alone.


7. BUDGET

- Engineering, M1-M4 (~130 hours part-time): $8,000
- RPC and market-data access (hard 40,000 calls/day cap; bursts hit provider limits and silently degrade collection): $1,800
- Documentation, writeups, dataset packaging: $1,400
- Contingency: $800
- Total: $12,000

All funding buys engineering time and the data access required to keep measurement honest. No trading capital, no token, no marketing.


8. RISKS AND HONEST LIMITATIONS

- The headline result is negative. The deliverable is the instrument and the method; that result is what validates them. This is not a proposal for a profitable trading product.
- One asset class, modest n. Micro-cap Solana tokens, a few thousand signals, one wallet universe; the harness is designed to be re-pointed.
- Upstream fragility. Public RPC and price endpoints rate-limit under load; the failure modes are visible in the data and documented, not eliminated.
- Solo, part-time. Stated plainly: one person, ~10 hours/week. The scope above is sized for that.


9. NOT PROPOSED

No live trading, ever, and none is possible in this design: the harness holds no keys, signs nothing and places no orders, and a self-check refuses to start if any signing path exists in the codebase. No token, no fund, no advice. This is measurement infrastructure.


Repository: https://github.com/ivanzoo3-14/solana-copy-trading-kill-test - the writeup, the frozen pre-registration, and the probes that re-derive every number above are in it.
