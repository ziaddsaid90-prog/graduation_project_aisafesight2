
from pathlib import Path
import hashlib

# ==========================================
# 1. DATASET PATH
# ==========================================

ROOT = Path(r"D:\TITAN_AI_Dataset").resolve()

if not ROOT.exists() or ROOT.name != "TITAN_AI_Dataset":
    raise ValueError("Wrong dataset folder! Check ROOT path.")

print("Dataset ROOT:", ROOT)


# ==========================================
# 2. SETTINGS
# ==========================================

EXCLUDED = {
    "framing",
    "framing_augmented",
    "duplicates_quarantine",
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp"
}

# Expected number from our reviewed preview
EXPECTED_DUPLICATES = 31


# ==========================================
# 3. HASH FUNCTION
# ==========================================

def get_hash(path):
    sha = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(chunk)

    return sha.hexdigest()


# ==========================================
# 4. PREFER ORIGINAL FILENAMES
# ==========================================

def preferred_file(path):
    name = path.stem.lower()

    unwanted_suffixes = (
        " (1)", " (2)", " - copy", "_copy", " copy"
    )

    return not name.endswith(unwanted_suffixes)


# ==========================================
# 5. FIND DUPLICATES
# ==========================================

def find_duplicates():

    all_duplicates = []
    total_checked = 0

    print("\n========== SCANNING DATASET ==========")

    for folder in ROOT.iterdir():

        if not folder.is_dir():
            continue

        if folder.name.lower() in EXCLUDED:
            print(f"\nSKIPPED: {folder.name}")
            continue

        hashes = {}

        for image_path in folder.rglob("*"):

            if not image_path.is_file():
                continue

            if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            total_checked += 1

            try:
                file_hash = get_hash(image_path)

            except OSError as error:
                raise RuntimeError(
                    f"Could not read {image_path}: {error}"
                )

            hashes.setdefault(file_hash, []).append(image_path)

        folder_duplicates = 0

        for file_hash, files in hashes.items():

            if len(files) < 2:
                continue

            # Prefer original filenames without copy suffixes
            files.sort(
                key=lambda p: (
                    not preferred_file(p),
                    str(p).lower()
                )
            )

            keep = files[0]
            duplicates = files[1:]

            for duplicate in duplicates:
                all_duplicates.append((keep, duplicate))
                folder_duplicates += 1

        print(f"\nFOLDER: {folder.name}")
        print(f"Duplicates found: {folder_duplicates}")

    return all_duplicates, total_checked


# ==========================================
# 6. REVIEW AND DELETE
# ==========================================

def main():

    duplicates, total_checked = find_duplicates()

    print("\n========== REVIEW ==========")
    print(f"Images checked: {total_checked}")
    print(f"Duplicates found: {len(duplicates)}")

    for keep, duplicate in duplicates:

        print("\nKEEP:", keep.relative_to(ROOT))
        print("DELETE:", duplicate.relative_to(ROOT))

    # Safety check
    if len(duplicates) != EXPECTED_DUPLICATES:

        print("\nSTOP: Duplicate count changed!")
        print("Expected:", EXPECTED_DUPLICATES)
        print("Found:", len(duplicates))
        print("No files were deleted.")
        return

    print("\n========== DELETE CONFIRMATION ==========")

    confirmation = input(
        '\nType DELETE 31 EXACT DUPLICATES to continue: '
    )

    if confirmation != "DELETE 31 EXACT DUPLICATES":

        print("\nCancelled. No files were deleted.")
        return

    # Delete only after confirmation
    deleted_count = 0

    for keep, duplicate in duplicates:

        duplicate.unlink()
        deleted_count += 1

        print(
            f"DELETED: {duplicate.relative_to(ROOT)}"
        )

    print("\n========== FINAL SUMMARY ==========")
    print(f"Images checked: {total_checked}")
    print(f"Duplicates deleted: {deleted_count}")
    print("Original images preserved.")
    print("Cleaning completed successfully.")


if __name__ == "__main__":
    main()
