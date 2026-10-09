# CHANGELOG

<!-- version list -->

## v1.1.0 (2026-10-08)

### Bug Fixes

- **accounts**: Credential-write boundary — secure-storage mirror, .storage-write, ops lock, version
  gate
  ([`4a8c81f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4a8c81f5d37b5f794fae17987d9ed892a27c7cde))

- **accounts**: Launcher gates on the shared claude contract
  ([`fc46b22`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/fc46b228021d709bf22b14664e9011842ebb10ee))

- **accounts**: Strip credential-supply and redirect env from the login child
  ([`7a47e87`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/7a47e87e3db309a4396482cdf5c0dc2537108690))

- **auto**: Escalation reuses serve-fresh cache rows
  ([`eb1c3e6`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/eb1c3e68a7a484af1b263b59e56783c21e78219a))

- **ci**: Contents: read per job — zero-scope token can't clone private repo
  ([`85eb44c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/85eb44c3b7ad3468c1eb0c957aec9e348719f772))

- **ci**: Gitleaks gets GITHUB_TOKEN — unauthenticated owner check flakes
  ([`2851ee1`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2851ee14dccffbdcdb4d40e25a1940d82665a93e))

- **ci**: Mutants cache key — hash once, before pytest writes test/ pyc
  ([`2d5a588`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2d5a588ac0f842b72543b5d0d58b0a91d936572d))

- **ci**: Partition mutants cache by test-tree hash — stale verdicts
  ([`9f03fb9`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/9f03fb99e1ece2bce3b15612a04ecdbf1feeca86))

- **ci**: Sha-keyed concurrency — main pushes no longer self-cancel
  ([`3b5ff3c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3b5ff3c992b03e6585b8fca06e9e039e08f217f0))

- **cli**: Argv=None deferral and NO_COLOR leak
  ([`53f9928`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/53f99285732a7fb37ee09cdda37f23fa3c0e827c))

- **cli**: Surface lock timeouts as errors not tracebacks
  ([`60504fd`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/60504fdaffbd0e47b632d0abb7874215e2a88715))

- **test**: Kill env-dependent mutants — TZ pin + quoted label assert
  ([`2ea8687`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2ea8687a1c6b249571500c8086f353ff1d0fb9e7))

- **test**: Stub claude in switch e2e — ambient binary isn't on CI PATH
  ([`e7c1d05`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/e7c1d0518ad345c20218a940bade222744ff9183))

- **test**: Whitespace-normalize argparse usage asserts — 3.13 rewraps
  ([`cddbe08`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/cddbe0859382d72994d38bce01e1dab37407c6a4))

### Build System

- **deps**: Add docs dependency-group — mkdocs-material
  ([`3c39e5a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3c39e5a667a4917afdda18552032df2e71c55fe8))

- **deps**: Build extra pins uv for the release build command
  ([`ad47c1d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/ad47c1dbc56ba98f704a6798bef23624d657a7ae))

- **deps**: Dev-pin actionlint-py — workflow lint joins the local gate
  ([`3de00a8`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3de00a81dde30291a5e399a154484051ee03e54f))

- **deps**: Dev-pin zizmor and pip-audit
  ([`61946f5`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/61946f566f10a4f8815c28097c7b108f37973448))

- **python**: Support >=3.11 — PEP-695 generics to TypeVar
  ([`310bec2`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/310bec2d0a333e06598e160ef7ccb1f79722e259))

- **release**: PSR cuts releases locally — uv-native build command
  ([`58de507`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/58de5079b9cbedeee275d3951ebb878acc7f3c11))

- **release**: Release branches join the main release group
  ([`0beb358`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/0beb358b67ea6480f5c55585796815d25214b3ec))

- **release**: Semantic-release config — version_toml, v-tags, uv relock build
  ([`5547428`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/55474283a51e18f0642e76daf79436addd4889ec))

### Chores

- Ship M10 — claude-version contract gate
  ([`4444ad1`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4444ad129a3b1c1d8445989b9c9589c39b80f76a))

- Ship M11 — tui ergonomics refactor
  ([`00c251e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/00c251ed763468e744a2672a3439924ce73f1fa7))

- **agents**: Add /next-task skill, retire prompt-execution scratch
  ([`e892bd6`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/e892bd617fff242fa22acaabcdb2fdd50c126f2a))

- **deps**: Import-linter 2.11 -> 2.15
  ([`21663ce`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/21663ce92f91dc849eaf5fc53adbd8e038a9a62f))

- **deps**: Mutmut 3.7.0 -> 3.8.0
  ([`530c172`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/530c1729fbe47ca82e3ee81b587c594f4c99c274))

- **deps**: Patch bumps + urllib3 2.8.0 security fix
  ([`b6c1fda`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/b6c1fda4cc508e89636ce069ab825a13af3a183f))

- **deps**: Pytest-asyncio 1.3.0 -> 1.4.0
  ([`27fe72e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/27fe72ecb4259b97ef0b62bad423a71d8ce93a02))

- **deps**: Ruff 0.15.17 -> 0.16.10
  ([`7b8fb52`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/7b8fb524068d744b3b50c18668491efda646b30b))

- **hooks**: Pre-commit-hooks v5.0.0 -> v6.0.0
  ([`674ba01`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/674ba01610115864781fe182743ce3a2522e0d16))

- **license**: Add MIT LICENSE and SPDX metadata
  ([`0973f92`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/0973f921d5c92820f5eb8a68a7c606ea046f6ebf))

- **pre-commit**: Mkdocs build --strict hook — site joins the gate
  ([`ca3b67c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/ca3b67c1c7c991a8c134ba392adf335d6e1f0e35))

- **repo**: Move process machinery to maintainer/
  ([`c5a5fd2`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/c5a5fd2561120792401b46d670ae34450c45f5b9))

- **repo**: Pre-public sweep — ignore .claude/, set repo metadata
  ([`a60344c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a60344c4371e61ef2f691430c75672e816ffd9c2))

- **repo**: Scrub internal pointers before going public
  ([`46b2086`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/46b208622e877e3edf59f2218bd70301e820a098))

- **security**: Gitleaks config — allowlist known non-secrets
  ([`1c3cfad`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1c3cfad6fa552fd112928b1163ac661a748e2c93))

- **slice**: Ship SL-010 — credential-write boundary
  ([`f513bba`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f513bbad5986f1ce82175154094e87988718e15b))

### Continuous Integration

- **github**: Cache mutmut workdir, gate timeout 60→120min
  ([`825f688`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/825f68833c67bf7c3cb6a1c39b62ce230471de58))

- **github**: Ci.yml — gate job + 3.11/3.12/3.13 test matrix
  ([`ed83c0d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/ed83c0db6eeb031559fe672a60f33f1ba12f8b3b))

- **github**: Codeql job — python SAST, visibility-gated
  ([`a712e77`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a712e77144bc7208236b3eba16b8219f370c0109))

- **github**: Dependabot — uv + github-actions, weekly
  ([`3daaf94`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3daaf94e2803840731ebb1c7af6b83b7d5f05290))

- **github**: Docs.yml — docs check + visibility-gated Pages deploy
  ([`3af8aeb`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3af8aebb30edae32defc5054cd263c20781b473b))

- **github**: Extract setup-env composite action
  ([`eecca7f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/eecca7fc587c74346bb2e7dc45f16a33a17b17c1))

- **github**: Pin ubuntu-24.04 runners
  ([`78baef3`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/78baef33edc47abac12fe17c59a2417bdedeea24))

- **github**: Scanner jobs — pip-audit, zizmor, gitleaks
  ([`f75bbc3`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f75bbc3b25a95b1e1d150f70eca5a78a8584ae28))

- **github**: Scorecard workflow — OSSF checks, visibility-gated
  ([`f356a1d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f356a1d420bf3e42cc7d957ac53a25adf10802f0))

- **github**: Split scanner battery into security.yml
  ([`aa18efc`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/aa18efced34ab034d63b11927525e252b7ca91b0))

- **release**: Publish workflow — tag-triggered, CI never pushes to main
  ([`5ba4392`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/5ba439208e453e915493e606f36cb62446eb8892))

- **release**: Release workflow — PSR on main, TestPyPI + reviewer-gated PyPI
  ([`7484dc2`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/7484dc271046fcbf64e6ee2d90d56b9e730ed3bf))

### Documentation

- Make code and test comments self-contained
  ([`56917f9`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/56917f98b8d329c752adcb2aedeb69b5bf851b3f))

- **adr**: Adopt upstream MADR template
  ([`8191aaa`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/8191aaa92119eda0c819bb72d40724a897536602))

- **adr**: ADR-0001 — maintainer/ paths + publishability rule
  ([`7d23e34`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/7d23e342c70567798db3ee35e81103bdf2a3331d))

- **adr**: Claude-version contract gate — band model, override, re-verification
  ([`65bf3c1`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/65bf3c1ad65cafdd7131c0b010971754c82fb742))

- **adr**: Credential-write boundary — ADR-0014, secure-storage mirroring, ops lock
  ([`878782e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/878782e0e62db3cfde087708ed26396502f27bf2))

- **adr**: Retrofit ADR-0001…0015 to upstream MADR
  ([`353e36e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/353e36e384ee7c3bb78c21f624dabbd9c48e4e6c))

- **architecture**: Arc42 §1 audit + §7 Deployment + §12 Glossary
  ([`d9f17a3`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/d9f17a396b6775f55caccd1e6b456c52d2ec9dbd))

- **backlog**: Insert M15-M17 public-readiness milestones; release renumbered M18
  ([`bdc528f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/bdc528fe6038809d16af781f6c29210e360a9936))

- **backlog**: Next-task skill + docs/dev physical split decisions into M15-M17
  ([`d0e7aeb`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/d0e7aebe9b2cd94541d502175633cda2793207e9))

- **backlog**: Open M14 — PyPI release pipeline
  ([`02e431c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/02e431c90e8c255cb5a8abbb38bc12fc3d4e4085))

- **backlog**: Ship M12 TUI UX affordances
  ([`a43476e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a43476e2cceee454069850b7e6d5f49f41f414f7))

- **backlog**: Ship M13 CLI UX
  ([`46821ae`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/46821ae27b417d3977652fac0eee437d44c067f6))

- **backlog**: Ship M14 — CI + supply-chain gate live and proven
  ([`2c763d5`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2c763d54a130898ac374ce007f3168146f3d2469))

- **backlog**: Ship M15 — docs standardization pass
  ([`1839ae9`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1839ae972a88c8621edb50802cb5c41c7ba3fbd8))

- **backlog**: Ship M16 — workflow restructure to reference grade
  ([`4b2fd4b`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4b2fd4bd1d5559fc727afc753071925f2fa8bbe5))

- **backlog**: Ship M17 — docs site live on GitHub Pages
  ([`f41f3e9`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f41f3e95e09e8a38828a0f5e5bae0f5130bfee9b))

- **backlog**: Split release work — M14 CI+supply-chain, M15 PyPI
  ([`d796274`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/d796274637d7c42efb5dc1044a231a0078bd1ee3))

- **github**: Community health files
  ([`080b74d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/080b74d5878280f522d03f115bddb12f6fc8b7ba))

- **readme**: Credit adapted upstream work; fix python floor
  ([`8f8af7e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/8f8af7ea5af65fe16b63bf0d57f5d89752f8ccdb))

- **readme**: Slim acknowledgments; move license text to NOTICE
  ([`2e0f1a4`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2e0f1a446e0d1be733e52d611d3e22cd0fc2b022))

- **release**: Ruleset binds merges only — drop the bypass-actor claim
  ([`897d0f5`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/897d0f586f8f5bd265342c4393257ff25538dfbe))

- **repo**: Audit pass — stale facts, dead conventions, broken links
  ([`a8c9639`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a8c9639c62018009bf35df53f000ffe67655df95))

- **repo**: README + pyproject urls — M17 T8
  ([`f673a24`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f673a2471c0a3c59a6c3d84c7fd7d785abd81b83))

- **research**: M14 CI+supply-chain and M15 release evidence
  ([`2f69ce3`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2f69ce3e2262df84345cbe6c9aefeb478bb35f5b))

- **site**: Getting-started — installation + quickstart
  ([`3bfb223`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3bfb223dfafa17c2ab3b0924580cda2ba77b7c92))

- **site**: Guides — switching, auto-switching, scripting, diagnostics
  ([`c4eca5a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/c4eca5a89732656346658176fa5ebcba57a4f519))

- **site**: Mkdocs.yml + index.md — Material config, Internals nav
  ([`4b54b71`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4b54b71cdab10b44d1451ffe91c7cb9fd2f700d3))

- **site**: Reference pages — cli, json-output, settings, env vars
  ([`4df5df7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4df5df746e6a667cf14bbedd452370d5083ae77e))

- **slice**: Mark T1 license + T2 history scan done
  ([`cd9850f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/cd9850f90ccd3256d8b984b205d695b82ba4f060))

- **slice**: Mark T10 Visual/Strip renderer done
  ([`f60e97a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/f60e97a9acc9c067ff7d1bc86e2930c37dc5bd1a))

- **slice**: Mark T11 branded loading indicator done
  ([`845ee01`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/845ee0167d306554e8f2b93f4d8a79ad96ca74fd))

- **slice**: Mark T3 shipped
  ([`b566e61`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/b566e616b7f38870bcf15b012ed85703870524d7))

- **slice**: Mark T4 busy throbber done
  ([`83226dd`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/83226dd464033cfa809da7b92580f239d5847069))

- **slice**: Mark T4–T10 done — 3.11 floor, workflows, scanners, dependabot
  ([`14833ec`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/14833ecf9ec17634f0201965474f241915f31d2c))

- **slice**: Mark T5 terminal title done
  ([`0f782d6`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/0f782d6593784351d251bd7e01f0638da066ee18))

- **slice**: Mark T6 settings read path done
  ([`1ec7a2a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1ec7a2abc33055973cb903cafefe0b108576807a))

- **slice**: Mark T7 settings write path done
  ([`dad4826`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/dad4826892595c7ccf55b77343af220d1471fc7f))

- **slice**: Mark T8 command palette done
  ([`c3130b7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/c3130b7c214b0f7c1673065ed3799cf1e7c5cf27))

- **slice**: Mark T9 narrow breakpoints done
  ([`a5d4fe7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a5d4fe71ac62e5e97dde7cd46c104db0d82a4453))

- **slice**: Open M10 / SL-011 — claude-version contract gate
  ([`434bfa7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/434bfa7f984ffe00d2db14fe7a1202aae71778e4))

- **slice**: Open M11 / SL-012 — toad-informed UX roadmap + TUI ergonomics
  ([`04b7226`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/04b7226723c9f87d541bfccdf04b512b07f35778))

- **slice**: Open M12 / SL-013 — TUI UX affordances
  ([`148ca11`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/148ca11da610c6ca22d11bfc10fbbed94ee21635))

- **slice**: Open M13 / SL-014 — CLI UX
  ([`d1af44f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/d1af44f13a22b7ae0491ee6251363d6a0944b46d))

- **slice**: Open M14 / SL-015 — CI + supply-chain gate
  ([`6b57e39`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/6b57e3969bfcccce72d58491f5298dc695396623))

- **slice**: SL-015 T3 checked — repo public, sweep clean
  ([`5480102`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/54801027776ae241a0945da1917af4d57f1f93f3))

- **slice**: SL-016 PRD for M15 — docs standardization pass
  ([`76e404a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/76e404abfefbf7dd8b5ea86c876da606f0d5f644))

- **slice**: SL-017 PRD for M16 — workflow restructure
  ([`9fc7dcf`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/9fc7dcfaeee78be440837fb6cf07a56e5ca298ed))

- **slice**: SL-018 PRD for M17 — docs site on GitHub Pages
  ([`2b1cb2f`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2b1cb2febbf4a0cb3661f5723e34a20eb9c62168))

- **slice**: SL-018 T1–T7 checked — pre-flip leg complete
  ([`498dfaf`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/498dfafeb1d39aff32de730e61391416baab4f60))

- **slice**: SL-019 PRD for M18 — PyPI release pipeline
  ([`732b425`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/732b425c35949c2cacfd5b39b90053a631f37935))

- **slice**: SL-019 — attrs-model pivot recorded, T1/T3 superseded
  ([`3528abd`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/3528abd894aa51dbba1e670daba7608366916374))

### Features

- **accounts**: Gate the switch transaction on the claude contract
  ([`1f10f6e`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1f10f6e0b375dad1c4ce05c4bf80de7b82d281d6))

- **accounts,usage**: ClaudeContractPort + subprocess probe adapters + fake
  ([`8ea95f7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/8ea95f74d66755dd53d5e8939f5a71f84cd719d1))

- **cli**: Bare cam opens the TUI on an interactive terminal
  ([`3464815`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/34648157faf0a6b41431f9603a174c21758f8455))

- **cli**: Cam --version
  ([`a562337`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a56233747c2fcd9207c21dce4ade258a7346b422))

- **cli**: Cam doctor — seven-section diagnostics report
  ([`b504a7b`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/b504a7bd97e3211b8a0b2704dfbc27b7b7349dbe))

- **cli**: Severity-colored human output for auto events and chrome
  ([`648a49c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/648a49c358080f2b83b7a39b0206ae0e2e3e3f54))

- **cli**: Surface contract refusals as a distinct error type
  ([`30b1830`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/30b183029b240c326187698940cf8cb7db00abc4))

- **shared**: Claude contract model — band check, probe, override, refusal
  ([`d268b9a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/d268b9a83a57ce82659c66d4caefc0cdd863c6fe))

- **tui**: Branded .loading cover via get_loading_widget
  ([`56791cb`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/56791cbd7933ffa7240d4e7a8dce31bbfe649f9a))

- **tui**: Busy throbber on title rows
  ([`73aa695`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/73aa695f7a6d629beedb05667a2f2797ea64bf6d))

- **tui**: Chrome widgets refuse text selection
  ([`bf05cb8`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/bf05cb8c23537a1d1b9ecd325bc6a026fa6ca7f8))

- **tui**: Command palette — nav, actions, per-account switch hits
  ([`1261d93`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1261d931878386564dbb0fa74c5164e96b376472))

- **tui**: F1 help panel + binding groups, tooltips, key display
  ([`7d36138`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/7d36138a790b6cb42fc7238479a1e1b4027bf6d0))

- **tui**: Generated settings screen — read path
  ([`107c93d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/107c93dd5e3c39dd8e0ab79d71c32d7cb7a90ecf))

- **tui**: Menu key accelerators
  ([`5e9af2d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/5e9af2d38fc5c25fa30c4f669420916af2ebd328))

- **tui**: Narrow-terminal breakpoints collapse minis
  ([`6395d17`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/6395d174a50199f26d58e47c2a43411e6a813093))

- **tui**: Settings write path — schema-driven edits persist
  ([`9289226`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/92892262a13a1e33a444d6fcccee18438e7503af))

- **tui**: Terminal window title + unfocused-completion blink
  ([`cd7af26`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/cd7af26392c84207fbddedf2a005efe71c9236dd))

- **tui**: Visual/Strip renderers for bars, cards, and minis
  ([`4cfce3b`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/4cfce3b761f24da97dfc1088fd695b65bd1354c0))

- **usage,auto**: Gate the refresh grant on the claude contract
  ([`ce9cf9d`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/ce9cf9d5bbefa48d139a07ce693ce2d756038868))

### Refactoring

- **cli**: HumanOutput seam — all human prints route through it
  ([`42c028c`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/42c028ce121988e8186f7da7c56c518b349b7bdf))

- **shared**: One severity ramp in shared/palette.py
  ([`a52f8dc`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/a52f8dcbd3015ff76193f230a0971c7e4e465396))

- **tui**: @on selectors, AUTO_FOCUS, focus_chain
  ([`852259a`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/852259a58da48610969e46e876fcffbecdb4afad))

- **tui**: @work decorators for the blocking workers
  ([`1d237f1`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1d237f186891c781fdc955a6d02ac813680406c3))

- **tui**: Getters.query_one descriptors for queried widgets
  ([`1a37ec4`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/1a37ec49bcd5381193d98564b9d84ef8e496d1c9))

- **tui**: PAUSE_GC_ON_SCROLL + gc.freeze startup heap
  ([`2a93192`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/2a9319232d7429952a40e67c0a836cfe64947bd0))

- **tui**: Push_screen_wait confirm_remove, data_bind view to card
  ([`dd991e7`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/dd991e74c81b9c157b2f27cc7f9c4bcb21d4417f))

### Testing

- **cli**: Pin the composition root's contract-probe wiring
  ([`73170a3`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/73170a341ce2594d905949db22cbbb76a5fa9646))

- **mutation**: Pin the survivors a fresh mutmut 3.8.0 full pass exposed
  ([`37a4bf4`](https://github.com/dmenezesgabriel/claude-acc-manager/commit/37a4bf4e57c553e7b7ba4c130791a486cd21f37d))


## v1.0.0 (2026-10-03)

- Initial Release
