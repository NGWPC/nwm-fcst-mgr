import json


def transform_component(comp):
    """
    Transform a single component dictionary to include only selected Git fields.

    The transformation rules are:
      - Always include 'commit_hash' and 'build_date'.
      - If 'tags' is non-empty, include the 'tags' field (renamed to 'release').
      - If 'tags' is empty, include 'branch', 'author', 'message', and 'commit_date'.
      - Recursively transform nested 'modules' (if present).

    :param comp: A dictionary containing Git information for a component.
    :return: A new dictionary with only the desired fields.
    """
    new_comp = {
        "commit_hash": comp.get("commit_hash", ""),
        "build_date": comp.get("build_date", "")
    }
    if comp.get("tags", "").strip() == "":
        # If tags is empty, include branch, author, message, and commit_date.
        new_comp["branch"] = comp.get("branch", "")
        new_comp["author"] = comp.get("author", "")
        new_comp["message"] = comp.get("message", "")
        new_comp["commit_date"] = comp.get("commit_date", "")
    else:
        # If tags is non-empty, include tags.
        new_comp["release"] = comp.get("tags", "")

    # Process nested modules recursively, if present
    if "modules" in comp and isinstance(comp["modules"], list):
        new_modules = []
        for module_obj in comp["modules"]:
            # Each module is an object with one key-value pair.
            for mod_name, mod_data in module_obj.items():
                new_modules.append({mod_name: transform_component(mod_data)})
        new_comp["modules"] = new_modules

    return new_comp


def recursive_print(d: dict, indent: int = 0) -> None:
    """
    Recursively print all key/value pairs from a dictionary.

    For each key-value pair:
      - If the value is a dictionary, print the key on one line and then recurse into that dictionary.
      - If the value is a list, print the key on one line and then iterate through the list;
        for each element that is a dictionary, recurse into it; otherwise print the element on a separate line.
      - Otherwise (if the value is a string or other non-dict, non-list), print the key and value on one line.

    :param d: The dictionary to print.
    :param indent: The current indentation level (number of spaces).
    """
    for key, value in d.items():
        if isinstance(value, dict):
            print(" " * indent + f"{key}:")
            recursive_print(value, indent + 2)
        elif isinstance(value, list):
            print(" " * indent + f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    recursive_print(item, indent + 2)
                else:
                    print(" " * (indent + 2) + str(item))
        else:
            print(" " * indent + f"{key}: {value}")


def print_git_info(git_info_file: str):
    """
    Read the specified git_info JSON file, transform its contents, and log all key/value pairs recursively.

    The output will print top-level keys (such as 'ngen') as well as keys for nested modules (such as 'LASAM').

    :param git_info_file: Path to the JSON file containing Git information.
    """
    try:
        with open(git_info_file, 'r') as f:
            git_info = json.load(f)
    except FileNotFoundError:
        print(f'{git_info_file} not found')
        return
    except json.decoder.JSONDecodeError as e:
        print(f"Error reading {git_info_file}: {e}")
        return

    if not git_info:
        print(f"Failed to retrieve git information from {git_info_file}.")
        return

    # Transform each top-level component without removing the keys.
    transformed_git_info = {key: transform_component(value) for key, value in git_info.items()}

    recursive_print(transformed_git_info)


def print_git_info_all():
    """
    Convenience function to print Git information from multiple JSON files.
    """
    print_git_info('/ngen-app/ngen-fcst_git_info.json')
    print_git_info('/ngen-app/ngen_git_info.json')
    print()
