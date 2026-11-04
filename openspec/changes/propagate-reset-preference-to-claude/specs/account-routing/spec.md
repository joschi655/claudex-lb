## MODIFIED Requirements

### Requirement: Reset-window preference propagation
All proxy account-selection surfaces SHALL pass the configured reset-window
preference into the canonical load balancer. This includes HTTP responses,
WebSocket responses, bridge requests, compact requests, transcription requests,
file-backed responses, Codex control requests, sticky fallback selection, the
Anthropic Messages relay, and the Claude next-account preview.

#### Scenario: WebSocket selection uses the configured window
- **GIVEN** dashboard settings set the reset-window preference to `primary`
- **WHEN** a WebSocket response request selects an account
- **THEN** the load balancer receives `primary` as the reset-window preference

#### Scenario: Claude relay spends the account whose 5h window closes first
- **GIVEN** dashboard settings enable earlier-reset preference with reset window `primary`
- **AND** two eligible Claude accounts of equal routing policy, one at `70%` resetting in
  four hours and one at `10%` resetting in twenty minutes
- **WHEN** a `/v1/messages` request selects an account under `fill_first`
- **THEN** the account resetting in twenty minutes is selected
