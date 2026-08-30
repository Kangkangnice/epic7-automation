# Shop refresh template sources

- Page, button and popup structure templates were cropped from current simulator fixtures captured on 2026-08-30.
- `covenant_candidate.png` and `mystic_candidate.png` originated from the open-source `Solunium/Epic-Seven-E7-Secret-Shop-Refresh` project.
- `mystic_candidate.png` is now verified against `mystic_row_live_20260831.png` from the current client (score 0.966). `mystic_price_current.png` is cropped from the current-client `mystic_purchase_confirm_live_20260831.png` fixture and proves the 280,000 gold price.
- `sold_out_0_of_1_current.png` is cropped from `mystic_purchased_row_live_20260831.png`. It marks the real post-purchase `0/1` slot as unavailable even though the dimmed purchase button remains visually present.
- Covenant still lacks current-client row and purchase-price fixtures. `LIVE_TRANSACTIONS_VERIFIED` must remain false until Covenant evidence and its regression tests exist.
