import json


def transform_component(comp):
    """
    Transform a single component dictionary to include only selected Git fields.

    The transformation rules are:
      - Always include 'commit_hash' and 'build_date'.
      - If 'tags' is non-empty, include the 'tags' field.
      - If 'tags' is empty, include 'branch', 'author', 'message', and 'commit_date'.
      - Recursively transform nested 'modules' (if present) with the same rules.

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


def print_git_info():
    """
    Read the combined git_info.json file, transform its contents,
    and log each key-value pair.

    If the file is not found or contains invalid JSON, logs a warning.
    """
    GIT_INFO = '/ngen-app/git_info.json'
    try:
        with open(GIT_INFO, 'r') as f:
            git_info = json.load(f)
    except FileNotFoundError:
        logger.warning(f'{GIT_INFO} not found')
        return
    except json.decoder.JSONDecodeError as e:
        print(f"Error reading {GIT_INFO}: {e}")
        return

    if not git_info:
        print(f"Failed to retrieve git information from {GIT_INFO}.")
        return

    # Assuming there is only one top-level key in the file.
    name, git_info_content = git_info.popitem()

    transformed_git_info = transform_component(git_info_content)
    for key, value in transformed_git_info.items():
        print(f'{key}: {value}')
