#!/usr/bin/env python3

import json
import pickle
import networkx as nx


def find_shortest_path(graph, start, end):
    try:
        path = nx.shortest_path(graph, start, end)
        out_path = [(n, graph.nodes[n]["node_type"]) for n in path]
        return out_path
    except nx.NetworkXNoPath:
        return None


def format_query(start, end, path, schema):
    query = f"Write a SQL query to find the relationship between the columns {start} and {end}. "
    query += "Here is are the schema of some relevant tables:\n\n"
    for node, node_type in path:
        if node_type == "table":
            table = next(t for t in schema if t["TableName"].upper() == node)
            query += f'Table: {table["TableName"]}\n'
            for column in table["Columns"]:
                key = column["Keys"]
                query += f'Column: {column["ColumnName"]}, Type: {column["DataType"]}, Key type: {key or "n/a"}\n'
            query += "\n"

    return query


if __name__ == "__main__":
    with open("schema.json", "r") as f:
        schema = json.load(f)

    with open("schema_graph.pkl", "rb") as f:
        graph = pickle.load(f)

    start, end = "ALOGP", "BLACK_BOX_WARNING"
    path = find_shortest_path(graph, start, end)
    print(format_query(start, end, path, schema))
