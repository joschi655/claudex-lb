# Tasks

- [x] 1. Pass `prefer_earlier_reset_accounts` / `prefer_earlier_reset_window` from dashboard
      settings in the Anthropic relay's account selection
- [x] 2. Same for the Claude next-account preview
- [x] 3. Route test: with the preference on and window `primary`, `/v1/messages` lands on the
      account whose 5h window closes first, against fill_first's fuller account; with it off,
      fill_first's choice stands
