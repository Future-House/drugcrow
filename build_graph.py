#!/usr/bin/env python3

import json
import networkx as nx
import pickle


def read_json_file(file_path):
    # Read JSON data from a file
    with open(file_path, "r") as file:
        data = json.load(file)
        return data


if __name__ == "__main__":
    file_path = "schema.json"
    data = read_json_file(file_path)
    graph = nx.Graph()

    for json_object in data:
        table_name = json_object["TableName"].upper()
        columns = json_object["Columns"]
        column_names = [column["ColumnName"] for column in columns]
        comments = [column["Comment"] for column in columns]

        if table_name not in graph:
            graph.add_node(table_name, node_type="table")

        table_dict = {}
        for e, (column, comment) in enumerate(zip(column_names, comments)):
            column = column.upper()
            if column not in graph:
                graph.add_node(column, node_type="column")

            graph.add_edge(table_name, column)

            if "Foreign key to " in comment:
                foreign_relationship = (
                    comment.split("Foreign key to ")[1].split("table")[0].lower()
                )
                if "the" in foreign_relationship:
                    foreign_relationship.split("the")[1].strip()

                foreign_relationship = foreign_relationship.strip().upper()
                if foreign_relationship not in graph:
                    graph.add_node(foreign_relationship, node_type="table")
                graph.add_edge(column, foreign_relationship)

    with open("schema_graph.pkl", "wb") as f:
        pickle.dump(graph, f)
