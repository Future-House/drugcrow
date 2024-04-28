#!/usr/bin/env python3

import json


def read_json_file(file_path):
    # Read JSON data from a file
    with open(file_path, "r") as file:
        data = json.load(file)
        return data


if __name__ == "__main__":
    file_path = "schema.json"
    data = read_json_file(file_path)

    graph_dict = {}
    for json_object in data:
        table_name = json_object["TableName"]
        columns = json_object["Columns"]
        column_names = [column["ColumnName"] for column in columns]
        comments = [column["Comment"] for column in columns]
        table_dict = {}
        for e, comment in enumerate(comments):
            column_name = column_names[e]
            if "Foreign key to " in comment:
                foreign_relationship = (
                    comment.split("Foreign key to ")[1].split("table")[0].lower()
                )
                if "the" in foreign_relationship:
                    foreign_relationship.split("the")[1].strip()
            else:
                foreign_relationship = None
            table_dict[column_name.lower()] = foreign_relationship
        graph_dict[table_name.lower()] = table_dict

    breakpoint()
    graph_dict[list(graph_dict.keys())[1]]
