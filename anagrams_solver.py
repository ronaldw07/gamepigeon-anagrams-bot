from collections import Counter
import time
import pyautogui
import easyocr
from PIL import Image, ImageFilter
import numpy as np
from os import path

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

def locate_with_retry(image_path, confidence, timeout=8, interval=0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            coords = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if coords:
                return coords
        except pyautogui.ImageNotFoundException:
            pass
        time.sleep(interval)
    return None

# Spend the whole round budget rather than racing, since dropped clicks over
# iPhone Mirroring cost far more points than unused seconds.
ROUND_SECONDS = 60
TIME_SAFETY_MARGIN = 12
MAX_CLICK_PAUSE = 0.09
RETRY_MIN_WORD_LENGTH = 4

def submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords):
    for click in word_click_order:
        pyautogui.click(individual_letter_boxes_coordinates[int(click)])
    pyautogui.click(enter_button_center_coords)

def execute_clicks(click_order, individual_letter_boxes_coordinates, enter_button_center_coords, round_start):
    deadline = round_start + ROUND_SECONDS - 2
    total_clicks = sum(len(word) + 1 for word in click_order)
    remaining = deadline - time.time() - TIME_SAFETY_MARGIN
    if total_clicks and remaining > 0:
        pyautogui.PAUSE = min(MAX_CLICK_PAUSE, remaining / total_clicks)

    for word_click_order in click_order:
        if time.time() > deadline:
            return
        submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords)

    # Leftover time means the first pass finished early. Resubmit the highest
    # scoring words to recover any lost to a dropped click; duplicates are
    # simply rejected by the game.
    while time.time() < deadline:
        for word_click_order in click_order:
            if time.time() > deadline:
                return
            if len(word_click_order) < RETRY_MIN_WORD_LENGTH:
                continue
            submit_word(word_click_order, individual_letter_boxes_coordinates, enter_button_center_coords)

def main():
    reader = easyocr.Reader(['en'])

    word_list = load_word_list()
    start_button_coords = locate_with_retry(path_to_file('images/start_button.png'), confidence=0.7)
    if not start_button_coords:
        print("No start button detected! Please open the game to the start screen and try again.")
        return
    # Divide by 2 for MacOS Retina display scaling
    start_button_center_coords = ((start_button_coords[0] + start_button_coords[2] / 2) / 2, (start_button_coords[1] + start_button_coords[3] / 2) / 2)

    pyautogui.click(start_button_center_coords, clicks=2, interval=0.2)
    round_start = time.time()

    enter_button_coords = locate_with_retry(path_to_file('images/enter_button.png'), confidence=0.7)
    if not enter_button_coords:
        print("No enter button detected!")
        return
    # Divide by 2 for MacOS Retina display scaling
    enter_button_center_coords = ((enter_button_coords[0] + enter_button_coords[2] / 2) / 2, (enter_button_coords[1] + enter_button_coords[3] / 2) / 2)

    try:
        empty_letter_boxes_unscaled_coords = pyautogui.locateOnScreen(path_to_file('images/seven_empty_letter_boxes_collection.png'), confidence=0.9)
        number_of_empty_letter_boxes = 7
    except pyautogui.ImageNotFoundException:
        try:
            empty_letter_boxes_unscaled_coords = pyautogui.locateOnScreen(path_to_file('images/six_empty_letter_boxes_collection.png'), confidence=0.9)
            number_of_empty_letter_boxes = 6
        except pyautogui.ImageNotFoundException:
            print("No letter boxes detected!")
            return

    if empty_letter_boxes_unscaled_coords:
        # 2.5% margin on the left and right to avoid detecting off of the iPhone screen
        # Divide by 2 for MacOS Retina display scaling
        screenshot_coordinates = (
            int((empty_letter_boxes_unscaled_coords[0] + empty_letter_boxes_unscaled_coords[2] / 40) / 2),
            int((empty_letter_boxes_unscaled_coords[1] + empty_letter_boxes_unscaled_coords[3]) / 2),
            int((empty_letter_boxes_unscaled_coords[2] - empty_letter_boxes_unscaled_coords[2] / 20) / 2),
            int(empty_letter_boxes_unscaled_coords[3] / 2)
        )
        # Divide by 2 for MacOS Retina display scaling
        individual_letter_boxes_center_coordinates = []
        for i in range(number_of_empty_letter_boxes):
            individual_letter_boxes_center_coordinates.append((
                int((empty_letter_boxes_unscaled_coords[0] + empty_letter_boxes_unscaled_coords[2] / number_of_empty_letter_boxes * i + empty_letter_boxes_unscaled_coords[2] / (number_of_empty_letter_boxes * 2)) / 2),
                int((empty_letter_boxes_unscaled_coords[1] + empty_letter_boxes_unscaled_coords[3] * 1.5) / 2)
            ))

    letters_screenshot = pyautogui.screenshot(region=screenshot_coordinates)
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
