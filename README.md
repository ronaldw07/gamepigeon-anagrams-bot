# Gamepigeon Anagrams Bot
Max out GamePigeon Anagrams games using iPhone mirroring!

<img src="examplescore.PNG" width="400">

> **Fork note (2026-09-06):** the prebuilt release executable does not work on
> every Mac. Button detection is pixel-size template matching, so the bundled
> images only match the display they were captured on. On a different screen
> resolution the bot fails with `No enter button detected!`. This fork runs from
> source, recalibrates the templates locally, and paces clicks to the round timer.
> See [What's different in this fork](#whats-different-in-this-fork).

**Steps**

1. Open the iPhone Mirroring app and launch a GamePigeon Anagrams game. Make sure you are on the screen with the start button.

<img src="startscreen.jpeg" width="400">

2. Run the solver from source (see [Setup](#setup)). You may need to grant your terminal Screen Recording and Accessibility permissions the first time, then restart the terminal.
3. Wait for the program to start! It usually takes around 20-30 seconds to load and start.

Notes September 9/6:
it doesnt work off the download as screen pixel dimensions r different.

## Stopping it mid-run

Press **Esc**. It is watched globally, so it works while the bot has the mouse.
This needs Terminal added under System Settings → Privacy & Security → Input
Monitoring; without it the script says so on startup and keeps running.

Failing that, slam the mouse pointer into any corner of the screen to trip
pyautogui's failsafe.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python anagrams_solver.py
```

## Recalibrating for your screen

If detection fails, the templates in `images/` do not match how the game renders
on your display. Regenerate them from your own screen:

1. With the game open on the letter tiles screen, capture what the bot sees:

   ```bash
   python3 -c "import pyautogui; pyautogui.screenshot().save('screen.png')"
   ```

2. Find where a template currently matches, lowering the confidence until it hits:

   ```bash
   python3 -c "
   import pyscreeze
   from PIL import Image
   im = Image.open('screen.png')
   for conf in [0.9, 0.8, 0.7, 0.6, 0.5]:
       try:
           print(conf, pyscreeze.locate('images/enter_button.png', im, confidence=conf))
           break
       except pyscreeze.ImageNotFoundException:
           print(conf, 'not found')
   "
   ```

3. Crop that region out of your screenshot and overwrite the template, then
   confirm it matches at 0.95:

   ```bash
   python3 -c "
   from PIL import Image
   Image.open('screen.png').crop((left, top, left + width, top + height)).save('images/enter_button.png')
   "
   ```

Repeat for `six_empty_letter_boxes_collection.png` and
`seven_empty_letter_boxes_collection.png` if the letter boxes are not detected.

## What's different in this fork

- **Retry button detection.** Upstream waited a fixed 1 second after clicking
  Start before looking for the Enter button. iPhone Mirroring can take longer
  than that to render, so detection is now retried for up to 8 seconds.
- **Recalibrated templates.** `enter_button.png` and
  `six_empty_letter_boxes_collection.png` were recropped from a real screenshot;
  the originals matched below the 0.7 confidence threshold on this display.
- **Click pacing tied to the round timer.** A fixed delay submitted words faster
  than iPhone Mirroring could register them, dropping words while leaving most of
  the 60 second round unused. The per-click delay is now derived from the number
  of clicks needed and the time remaining.
- **Resubmission pass.** Once the word list is exhausted, words of four letters
  or more are resubmitted until the round ends, recovering any lost to a dropped
  click. Duplicates are simply rejected by the game.

Measured on a 6-letter board (A,K,R,S,T,U): 66 of 70 possible words and 33,100
of 36,000 points, up from 31 of 54 words before these changes.
