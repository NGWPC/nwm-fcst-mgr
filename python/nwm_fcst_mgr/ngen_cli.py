"""Classes for building calls to the ngen command-line interface"""

import json
import os
import re


class NgenCLI:
    """ngen command-line interface command builder.
    See for details: https://github.com/NGWPC/ngen/blob/development/README.md"""

    def __init__(
        self,
        ngen_path: str,
        cats_path: str,
        cats_subset_ids: tuple[str] | None,
        nexus_path: str,
        nexus_subset_ids: tuple[str] | None,
        realization_config_path: str,
        partition_config_path: str | None,
    ):
        ### Arg 0
        self.arg_ngen_path = os.path.realpath(ngen_path)

        ### Arg 1
        self.arg_cats_path = os.path.realpath(cats_path)

        ### Arg 2
        if cats_subset_ids is None:
            self.arg_cats_subset_ids = "all"
        else:
            assert isinstance(cats_subset_ids, tuple)
            self.arg_cats_subset_ids = ",".join(cats_subset_ids)
        assert " " not in self.arg_cats_subset_ids

        ### Arg 3
        self.arg_nexus_path = os.path.realpath(nexus_path)

        ### Arg 4
        if nexus_subset_ids is None:
            self.arg_nexus_subset_ids = "all"
        else:
            self.arg_nexus_subset_ids = ",".join(nexus_subset_ids)
        assert " " not in self.arg_nexus_subset_ids

        ### Arg 5
        self.arg_realization_config_path = os.path.realpath(realization_config_path)

        ### Arg 6 (optional, and requires mpirun prepend)
        if partition_config_path:
            self.arg_partition_config_path = os.path.realpath(partition_config_path)
            self.n_procs = read_partition_count(partition_config_path)
        else:
            self.arg_partition_config_path = None
            self.n_procs = 1

    def ngen_cmd(self, as_string: bool = False) -> list[str] | str:
        """Build and return the ngen command as a list (for subprocess.Popen),
        adding mpirun and partition arguments as appropriate.
        Optionally return it as a string if as_string is True."""
        cmd = [
            self.arg_ngen_path,
            self.arg_cats_path,
            self.arg_cats_subset_ids,
            self.arg_nexus_path,
            self.arg_nexus_subset_ids,
            self.arg_realization_config_path,
        ]
        if self.arg_partition_config_path:
            if self.n_procs < 2:
                raise ValueError(
                    f"Expected self.n_procs to be at least 2 since self.arg_partition_config_path is truthy, but got {self.n_procs}"
                )
            cmd = ["mpirun", "-n", str(self.n_procs)] + cmd
            cmd.append(self.arg_partition_config_path)
        elif self.n_procs != 1:
            raise ValueError(
                f"Expected self.n_procs to be 1 since self.arg_partition_config_path is falsy, but got {self.n_procs}"
            )

        if as_string:
            # Confirm that there are no whitespace in any of the elements, which would break the string form.
            errors = []
            for i, el in enumerate(cmd):
                if bool(re.search(r"\s", el)):
                    errors.append(
                        ValueError(
                            f"Whitespace found in index {i}, {repr(el)} of cmd {repr(cmd)}"
                        )
                    )
            if errors:
                raise RuntimeError(errors)
            # This is a safe list to turn into a space-delimited cmd string
            cmd = " ".join(cmd)

        return cmd


def read_partition_count(partition_config_path: str) -> int:
    """Read the provided partition config file, determine the number of partitions, and return that number."""
    if not partition_config_path.endswith(".json"):
        raise ValueError(f"Expected a json file, got {repr(partition_config_path)}")
    with open(partition_config_path) as f:
        struc = json.load(f)
    parts = struc["partitions"]
    if len(parts) < 2:
        raise ValueError(
            f"Expected at least 2 partitions, got {len(parts)} in {repr(partition_config_path)}"
        )
    return len(parts)
