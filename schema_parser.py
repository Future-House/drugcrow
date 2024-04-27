#!/usr/bin/env python3

import json
import re


def parse_schema(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()

    schema = []
    current_table = None
    reading_data = False

    for line in lines:
        line = line.strip()
        if line.endswith(":"):
            if current_table is not None:
                schema.append(current_table)
            current_table = {"TableName": line[:-1], "Columns": []}
            description_lines = []
            reading_data = False
        elif current_table:
            if "KEYS" in line and "COLUMN_NAME" in line:  # Start reading the data
                reading_data = True
            elif reading_data:
                if line:  # Read data entries
                    data = re.split(
                        r"\s{2,}", line
                    )  # Assume at least two spaces as a separator
                    try:
                        column_entry = {
                            "Keys": data[0],
                            "ColumnName": data[1],
                            "DataType": data[2],
                            "Nullable": data[3] if len(data) > 3 else "",
                            "Comment": data[4] if len(data) > 4 else "",
                        }
                    except IndexError:
                        print(f"Error parsing line: {line}")
                        continue
                    else:
                        current_table["Columns"].append(column_entry)
            else:
                description_lines.append(line)
                # Optionally store and use description if needed elsewhere; currently not included in output format

    if current_table is not None:
        schema.append(current_table)

    return schema


schema = parse_schema("schema_documentation.txt")
with open("schema.json", "w") as file:
    json.dump(schema, file, indent=4)
