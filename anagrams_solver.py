from collections import Counter
import threading
import time
import pyautogui
import easyocr
from PIL import Image, ImageFilter
import numpy as np
from os import path
from pynput import keyboard
from Quartz import (
    CGDataProviderCopyData,
    CGEventCreateMouseEvent,
    CGEventPost,
    CGImageGetBytesPerRow,
    CGImageGetDataProvider,
    CGImageGetHeight,
    CGImageGetWidth,
    CGRectNull,
    CGWindowListCopyWindowInfo,
    CGWindowListCreateImage,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
    kCGNullWindowID,
    kCGWindowImageBoundsIgnoreFraming,
    kCGWindowListOptionIncludingWindow,
    kCGWindowListOptionOnScreenOnly,
)

# The bot owns the mouse while it plays, so the corner failsafe is hard to reach.
# Esc is watched globally instead.
stop_requested = threading.Event()

def start_kill_switch():
    def on_press(key):
        if key == keyboard.Key.esc:
            stop_requested.set()
            print("\nEsc pressed, stopping.")
            return False

    try:
        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()
        print("Press Esc at any time to stop.")
    except Exception as error:
        # Needs Input Monitoring permission; the corner failsafe still applies.
        print(f"Esc kill switch unavailable ({error}). Slam the mouse into a screen corner to stop.")

def path_to_file(filename):
    return path.abspath(path.join(path.dirname(__file__), filename))

def load_word_list(filename="anagrams_words.txt"):
    with open(path_to_file(filename), 'r') as word_list:
        return [line.strip().upper() for line in word_list if line.strip()]

def ocr(screenshot, reader):
    # Binarize the image
    img_array = np.array(screenshot.convert('L'))
    threshold = 30
    img_array = np.where(img_array < threshold, 0, 255).astype(np.uint8)
    binarized_letters = Image.fromarray(img_array)

    # detail=1 keeps the bounding boxes so letters can be ordered left to right.
    # Detection order alone is not positional, and a scrambled order maps every
    # word onto the wrong tiles.
    detections = reader.readtext(np.array(binarized_letters), allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ', detail=1)

    letters = []
    for box, text, _confidence in detections:
        text = str(text).strip().upper().replace(' ', '')
        if not text:
            continue
        left_edge = min(corner[0] for corner in box)
        width = max(corner[0] for corner in box) - left_edge
        # A single detection can span several tiles, so spread its characters
        # evenly across its own width to keep them in the right order.
        for index, character in enumerate(text):
            letters.append((left_edge + width * (index + 0.5) / len(text), character))

    letters.sort(key=lambda letter: letter[0])
    return ''.join(character for _x, character in letters)

def can_make_word_from_letters(word, letters):
    word_counter = Counter(word)
    letters_counter = Counter(letters)

    for letter, count in word_counter.items():
        if letters_counter[letter] < count:
            return False
    return True

def find_possible_words(letters, word_list):
    letters = letters.upper().replace(" ", "")

    possible_words = []
    for word in word_list:
        if can_make_word_from_letters(word, letters):
            possible_words.append(word)

    # Sort by length (longest first), then alphabetically
    possible_words.sort(key=lambda x: (-len(x), x))
    return possible_words

# Convert each word to numbers, 0 being clicking the left-most letter, 6 being clicking the right-most letter
def convert_word_list_to_click_order(word_list, letters):
    click_order = []
    for i in range(len(word_list)):
        word = word_list[i]
        click_order.append("")
        for letter in word:
            for j in range(len(letters)):
                if letters[j] == letter and str(j) not in click_order[i]:
                    click_order[i] += str(j)
                    break
    return click_order

def calculate_max_points(word_list):
    max_score = 0
    for word in word_list:
        if len(word) == 7:
            max_score += 3000
        elif len(word) == 6:
            max_score += 2000
        elif len(word) == 5:
            max_score += 1200
        elif len(word) == 4:
            max_score += 400
        elif len(word) == 3:
            max_score += 100
    return max_score

def display_results(words, letters):
    print(f"\nWords that can be made from '{letters}':")
    print("=" * 50)

    # Group words by length
    words_by_length = {}
    for word in words:
        length = len(word)
        if length not in words_by_length:
            words_by_length[length] = []
        words_by_length[length].append(word)

    # Display grouped by length
    for length in sorted(words_by_length.keys(), reverse=True):
        print(f"\n{length}-letter words ({len(words_by_length[length])} found, {calculate_max_points(words_by_length[length])} points):")
        words_in_length = words_by_length[length]
        # Display in columns for better readability
        for i in range(0, len(words_in_length), 5):
            row = words_in_length[i:i+5]
            print("  " + "  ".join(f"{word:<12}" for word in row))

    print(f"\nTotal words found: {len(words)}")
    print(f"Total points: {calculate_max_points(words)}")

# The templates in images/ were captured on a Retina screen, so every capture
# is brought to this many pixels per point before matching.
TEMPLATE_PIXELS_PER_POINT = 2

def find_mirroring_window():
    """(window id, (x, y, w, h)) of the iPhone Mirroring window in screen
    points, on whichever display it is, or None."""
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    matches = [
        w for w in windows
        if w.get("kCGWindowOwnerName") == "iPhone Mirroring"
        and w.get("kCGWindowName") == "iPhone Mirroring"
    ]
    if not matches:
        return None
    w = max(matches, key=lambda w: w["kCGWindowBounds"]["Width"] * w["kCGWindowBounds"]["Height"])
    b = w["kCGWindowBounds"]
    return w["kCGWindowNumber"], (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]))

def capture_window():
    """Screenshot of just the iPhone Mirroring window, scaled to the templates'
    Retina resolution, and the window's top-left corner in screen points.
    A full-screen grab only covers the main display and misses the window
    on an external monitor. Returns (None, None) if the window isn't open."""
    found = find_mirroring_window()
    if found is None:
        return None, None
    window_id, (x, y, w, h) = found
    image = CGWindowListCreateImage(
        CGRectNull, kCGWindowListOptionIncludingWindow, window_id, kCGWindowImageBoundsIgnoreFraming,
    )
    width, height = CGImageGetWidth(image), CGImageGetHeight(image)
    data = CGDataProviderCopyData(CGImageGetDataProvider(image))
    bgra = np.frombuffer(data, dtype=np.uint8).reshape(height, CGImageGetBytesPerRow(image) // 4, 4)
    screenshot = Image.fromarray(np.ascontiguousarray(bgra[:, :width, 2::-1]))
    target = (w * TEMPLATE_PIXELS_PER_POINT, h * TEMPLATE_PIXELS_PER_POINT)
    if screenshot.size != target:
        screenshot = screenshot.resize(target)
    return screenshot, (x, y)

def to_screen_point(x, y, window_origin):
    """Convert a position in a capture_window() screenshot to screen points."""
    return (window_origin[0] + x / TEMPLATE_PIXELS_PER_POINT,
            window_origin[1] + y / TEMPLATE_PIXELS_PER_POINT)

def click(point, pause=0.0):
    """Click with Quartz events, which reach displays left of or above the
    main one (negative coordinates)."""
    for kind in (kCGEventLeftMouseDown, kCGEventLeftMouseUp):
        CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, kind, point, kCGMouseButtonLeft))
    time.sleep(pause)

# The iPhone Mirroring window can come back a few percent smaller or larger after
# reconnecting, so templates are also tried slightly scaled.
TEMPLATE_SCALES = (1.0, 0.97, 1.03, 0.94, 1.06, 0.91, 1.09)

def locate_any_scale(image_path, confidence, screenshot):
    template = Image.open(image_path)
    for scale in TEMPLATE_SCALES:
        size = (round(template.width * scale), round(template.height * scale))
        scaled = template if scale == 1.0 else template.resize(size)
        try:
            return pyautogui.locate(scaled, screenshot, confidence=confidence)
        except pyautogui.ImageNotFoundException:
            pass
    return None

def locate_with_retry(image_path, confidence, timeout=8, interval=0.3):
    """Returns (box in the capture, window origin), or (None, None)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        screenshot, window_origin = capture_window()
        coords = locate_any_scale(image_path, confidence, screenshot) if screenshot else None
        if coords:
            return coords, window_origin
        time.sleep(interval)
    return None, None

# Spend the whole round budget rather than racing, since dropped clicks over
# iPhone Mirroring cost far more points than unused seconds.
ROUND_SECONDS = 60
TIME_SAFETY_MARGIN = 12
MAX_CLICK_PAUSE = 0.09
RETRY_MIN_WORD_LENGTH = 4

def submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords, pause):
    for letter_index in word_click_order:
        if stop_requested.is_set():
            return
        click(individual_letter_boxes_coordinates[int(letter_index)], pause)
    click(enter_button_center_coords, pause)

def execute_clicks(click_order, individual_letter_boxes_coordinates, enter_button_center_coords, round_start):
    deadline = round_start + ROUND_SECONDS - 2
    total_clicks = sum(len(word) + 1 for word in click_order)
    remaining = deadline - time.time() - TIME_SAFETY_MARGIN
    pause = MAX_CLICK_PAUSE
    if total_clicks and remaining > 0:
        pause = min(MAX_CLICK_PAUSE, remaining / total_clicks)

    for word_click_order in click_order:
        if time.time() > deadline or stop_requested.is_set():
            return
        submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords, pause)

    # Leftover time means the first pass finished early. Resubmit the highest
    # scoring words to recover any lost to a dropped click; duplicates are
    # simply rejected by the game.
    while time.time() < deadline and not stop_requested.is_set():
        for word_click_order in click_order:
            if time.time() > deadline or stop_requested.is_set():
                return
            if len(word_click_order) < RETRY_MIN_WORD_LENGTH:
                continue
            submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords, pause)

def main():
    start_kill_switch()
    reader = easyocr.Reader(['en'])

    word_list = load_word_list()
    start_button_coords, window_origin = locate_with_retry(path_to_file('images/start_button.png'), confidence=0.7)
    if not start_button_coords:
        print("No start button detected! Please open the game to the start screen and try again.")
        return
    start_button_center_coords = to_screen_point(start_button_coords[0] + start_button_coords[2] / 2, start_button_coords[1] + start_button_coords[3] / 2, window_origin)

    # The first click focuses the iPhone Mirroring window, the second presses Start.
    click(start_button_center_coords, pause=0.2)
    click(start_button_center_coords)
    round_start = time.time()

    enter_button_coords, window_origin = locate_with_retry(path_to_file('images/enter_button.png'), confidence=0.7)
    if not enter_button_coords:
        print("No enter button detected!")
        return
    enter_button_center_coords = to_screen_point(enter_button_coords[0] + enter_button_coords[2] / 2, enter_button_coords[1] + enter_button_coords[3] / 2, window_origin)

    screenshot, window_origin = capture_window()
    empty_letter_boxes_unscaled_coords = locate_any_scale(path_to_file('images/seven_empty_letter_boxes_collection.png'), 0.9, screenshot)
    if empty_letter_boxes_unscaled_coords:
        number_of_empty_letter_boxes = 7
    else:
        empty_letter_boxes_unscaled_coords = locate_any_scale(path_to_file('images/six_empty_letter_boxes_collection.png'), 0.9, screenshot)
        number_of_empty_letter_boxes = 6
    if not empty_letter_boxes_unscaled_coords:
        print("No letter boxes detected!")
        return

    left, top, width, height = empty_letter_boxes_unscaled_coords
    # The letter tiles sit one box-height below the empty boxes. 2.5% margin on
    # the left and right to avoid detecting off of the iPhone screen.
    letters_region = (int(left + width / 40), int(top + height), int(left + width - width / 40), int(top + 2 * height))
    individual_letter_boxes_center_coordinates = [
        to_screen_point(left + width / number_of_empty_letter_boxes * i + width / (number_of_empty_letter_boxes * 2), top + height * 1.5, window_origin)
        for i in range(number_of_empty_letter_boxes)
    ]

    letters_screenshot = capture_window()[0].crop(letters_region)
    letters = ocr(letters_screenshot, reader)

    print(f"Detected letters: {letters}")
    if not letters or len(letters) != number_of_empty_letter_boxes:
        print("Incorrect number of letters detected!")
        letters = input("Please enter the letters manually: ").strip().upper()

    possible_words = find_possible_words(letters, word_list)
    display_results(possible_words, letters)

    click_order = convert_word_list_to_click_order(possible_words, letters)
    execute_clicks(click_order, individual_letter_boxes_center_coordinates, enter_button_center_coords, round_start)

if __name__ == "__main__":
    main()
