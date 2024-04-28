import json
import os
from typing import Dict

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from modal import Image, Secret, Stub, asgi_app

stub = Stub("drugcrow")
web_app = FastAPI()
auth_scheme = HTTPBearer()

image = (
    Image.debian_slim(python_version="3.11")
    .pip_install(
        "langchain==0.1.16",
        "langchain-openai",
        "pandas",
        "numpy",
        "scipy",
        "matplotlib",
        "google-cloud-bigquery",
        "db-dtypes",
        "networkx"
    )
)
with image.imports():
    import os
    from langchain.agents import AgentExecutor
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    from langchain_openai import ChatOpenAI
    from google.cloud.bigquery.client import Client
    from langchain.agents import OpenAIFunctionsAgent, ZeroShotAgent
    import json
    import os.path
    from langchain_core.prompts import PromptTemplate
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

    with open("service-account.json", "w") as f:
        f.write(json.dumps())
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "service-account.json"
    client = Client()
    llm = ChatOpenAI(
        temperature=0.1,
        model="gpt-4-turbo",
        openai_api_key="",
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    # tools = []
    # agent_instance = AgentExecutor.from_agent_and_tools(
    #     tools=tools,
    #     agent=OpenAIFunctionsAgent.from_llm_and_tools(llm, tools),
    #     handle_parsing_errors=True,
    # )


@stub.function(image=image, gpu="a100")
def answer(question:str):
    found_columns = []
    json_objects = [
        {
            "TableName": "ACTION_TYPE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ACTION_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Type of action of the drug e.g., agonist, antagonist"
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "Description of how the action type is used"
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENT_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Higher-level grouping of action types e.g., positive vs negative action"
                }
            ]
        },
        {
            "TableName": "ACTIVITIES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ACTIVITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for the activity row"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ASSAY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the assays table (containing the assay description)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "DOC_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to documents table (for quick lookup of publication details - can also link to documents through compound_records or assays table)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the compound_records table (containing information on the compound tested)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to compounds table (for quick lookup of compound structure - can also link to compounds through compound_records table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Symbol constraining the activity value (e.g. >, <, =)"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Same as PUBLISHED_VALUE but transformed to common units: e.g. mM concentrations converted to nM."
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Selected 'Standard' units for data type: e.g. concentrations are in nM."
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Shows whether the standardised columns have been curated/set (1) or just default to the published data (0)."
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Standardised version of the published_activity_type (e.g. IC50 rather than Ic-50/Ic50/ic50/ic-50)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ACTIVITY_COMMENT",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Previously used to report non-numeric activities i.e. 'Slighty active', 'Not determined'. STANDARD_TEXT_VALUE will be used for this in future, and this will be just for additional comments."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "DATA_VALIDITY_COMMENT",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": None,
                    "Comment": "Comment reflecting whether the values for this activity measurement are likely to be correct - one of 'Manually validated' (checked original paper and value is correct), 'Potential author error' (value looks incorrect but is as reported in the original paper), 'Outside typical range' (value seems too high/low to be correct e.g., negative IC50 value), 'Non standard unit type' (units look incorrect for this activity type)."
                },
                {
                    "Keys": None,
                    "ColumnName": "POTENTIAL_DUPLICATE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "When set to 1, indicates that the value is likely to be a repeat citation of a value reported in a previous ChEMBL paper, rather than a new, independent measurement. Note: value of zero does not guarantee that the measurement is novel/independent though"
                },
                {
                    "Keys": None,
                    "ColumnName": "PCHEMBL_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Negative log of selected concentration-response activity values (IC50/EC50/XC50/AC50/Ki/Kd/Potency)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "BAO_ENDPOINT",
                    "DataType": "VARCHAR2(11)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding result type in BioAssay Ontology (based on standard_type)"
                },
                {
                    "Keys": None,
                    "ColumnName": "UO_UNITS",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding unit in Unit Ontology (based on standard_units)"
                },
                {
                    "Keys": None,
                    "ColumnName": "QUDT_UNITS",
                    "DataType": "VARCHAR2(70)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding unit in QUDT Ontology (based on standard_units)"
                },
                {
                    "Keys": None,
                    "ColumnName": "TOID",
                    "DataType": "INTEGER",
                    "Noneable": None,
                    "Comment": "The Test Occasion Identifier, used to group together related activity measurements"
                },
                {
                    "Keys": None,
                    "ColumnName": "UPPER_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Where the activity is a range, this represents the highest value of the range (numerically), while the PUBLISHED_VALUE column represents the lower value"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_UPPER_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Where the activity is a range, this represents the standardised version of the highest value of the range (with the lower value represented by STANDARD_VALUE)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SRC_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to source table, indicating the source of the activity value"
                },
                {
                    "Keys": None,
                    "ColumnName": "TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": "NOT None",
                    "Comment": "Type of end-point measurement: e.g. IC50, LD50, %inhibition etc, as it appears in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Symbol constraining the activity value (e.g. >, <, =), as it appears in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Datapoint value as it appears in the original dataset."
                },
                {
                    "Keys": None,
                    "ColumnName": "UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Units of measurement as they appear in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "TEXT_VALUE",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Additional information about the measurement"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TEXT_VALUE",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Standardized version of additional information about the measurement"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ACTION_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Foreign key to action_type table; specifies the effect of the compound on its target."
                }
            ]
        },
        {
            "TableName": "ACTIVITY_PROPERTIES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "AP_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for each record."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ACTIVITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "FK to ACTIVITY_ID in ACTIVITIES table."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": "NOT None",
                    "Comment": "The parameter or property type"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Symbol constraining the value (e.g. >, <, =)"
                },
                {
                    "Keys": None,
                    "ColumnName": "VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Numberical value for the parameter or property"
                },
                {
                    "Keys": None,
                    "ColumnName": "UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Units of measurement"
                },
                {
                    "Keys": None,
                    "ColumnName": "TEXT_VALUE",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Non-numerical value of the parameter or property"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Standardised form of the TYPE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Standardised form of the RELATION"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Standardised form of the VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Standardised form of the UNITS"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TEXT_VALUE",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Standardised form of the TEXT_VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMMENTS",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "A Comment."
                },
                {
                    "Keys": None,
                    "ColumnName": "RESULT_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "A flag to indicate, if set to 1, that this type is a dependent variable/result (e.g., slope) rather than an independent variable/parameter (0, the default)."
                }
            ]
        },
        {
            "TableName": "ACTIVITY_SMID",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "SMID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "FK to SMID in ACTIVITY_SUPP_MAP, and a FK to SMID in ACTIVITY_SUPP"
                }
            ]
        },
        {
            "TableName": "ACTIVITY_STDS_LOOKUP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "STD_ACT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "STANDARD_TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": "NOT None",
                    "Comment": "The standard_type that other published_types in the activities table have been converted to."
                },
                {
                    "Keys": None,
                    "ColumnName": "DEFINITION",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "A description/definition of the standard_type."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "STANDARD_UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "The units that are applied to this standard_type and to which other published_units are converted. Note a standard_type may have more than one allowable standard_unit and therefore multiple rows in this table."
                },
                {
                    "Keys": None,
                    "ColumnName": "NORMAL_RANGE_MIN",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The lowest value for this activity type that is likely to be genuine. This is only an approximation, so lower genuine values may exist, but it may be desirable to validate these before using them. For a given standard_type/units, values in the activities table below this threshold are flagged with a data_validity_comment of 'Outside typical range'."
                },
                {
                    "Keys": None,
                    "ColumnName": "NORMAL_RANGE_MAX",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The highest value for this activity type that is likely to be genuine. This is only an approximation, so higher genuine values may exist, but it may be desirable to validate these before using them. For a given standard_type/units, values in the activities table above this threshold are flagged with a data_validity_comment of 'Outside typical range'."
                }
            ]
        },
        {
            "TableName": "ACTIVITY_SUPP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "AS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for each record."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "RGID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Record Grouping ID, used to group together related data points in this table"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SMID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "FK to SMID in ACTIVITY_SMID."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": "NOT None",
                    "Comment": "Type of end-point measurement: e.g. IC50, LD50, %inhibition etc, as it appears in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Symbol constraining the activity value (e.g. >, <, =), as it appears in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Datapoint value as it appears in the original dataset."
                },
                {
                    "Keys": None,
                    "ColumnName": "UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Units of measurement as they appear in the original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "TEXT_VALUE",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Non-numeric value for measurement as in original dataset"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Standardised form of the TYPE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Standardised form of the RELATION"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Standardised form of the VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Standardised form of the UNITS"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TEXT_VALUE",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Standardised form of the TEXT_VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMMENTS",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "A Comment."
                }
            ]
        },
        {
            "TableName": "ACTIVITY_SUPP_MAP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ACTSM_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ACTIVITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "FK to ACTIVITY_ID in ACTIVITIES table."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SMID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "FK to SMID in ACTIVITY_SMID."
                }
            ]
        },
        {
            "TableName": "ASSAY_CLASS_MAP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ASS_CLS_MAP_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ASSAY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key that maps to the ASSAYS table"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ASSAY_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key that maps to the ASSAY_CLASSIFICATION table"
                }
            ]
        },
        {
            "TableName": "ASSAY_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ASSAY_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": None,
                    "ColumnName": "L1",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "High level classification e.g., by anatomical/therapeutic area"
                },
                {
                    "Keys": None,
                    "ColumnName": "L2",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Mid-level classification e.g., by phenotype/biological process"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "L3",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Fine-grained classification e.g., by assay type"
                },
                {
                    "Keys": None,
                    "ColumnName": "CLASS_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "The type of assay being classified e.g., in vivo efficacy"
                },
                {
                    "Keys": None,
                    "ColumnName": "SOURCE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Source from which the assay class was obtained"
                }
            ]
        },
        {
            "TableName": "ASSAY_PARAMETERS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ASSAY_PARAM_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Numeric primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ASSAY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to assays table. The assay to which this parameter belongs"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": "NOT None",
                    "Comment": "The type of parameter being described, according to the original data source"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "The relation symbol for the parameter being described, according to the original data source"
                },
                {
                    "Keys": None,
                    "ColumnName": "VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The value of the parameter being described, according to the original data source. Used for numeric data"
                },
                {
                    "Keys": None,
                    "ColumnName": "UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "The units for the parameter being described, according to the original data source"
                },
                {
                    "Keys": None,
                    "ColumnName": "TEXT_VALUE",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "The text value of the parameter being described, according to the original data source. Used for non-numeric/qualitative data"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TYPE",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Standardized form of the TYPE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_RELATION",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Standardized form of the RELATION"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Standardized form of the VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_UNITS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Standardized form of the UNITS"
                },
                {
                    "Keys": None,
                    "ColumnName": "STANDARD_TEXT_VALUE",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Standardized form of the TEXT_VALUE"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMMENTS",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Additional comments describing the parameter"
                }
            ]
        },
        {
            "TableName": "ASSAY_TYPE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ASSAY_TYPE",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": "NOT None",
                    "Comment": "Single character representing assay type"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_DESC",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Description of assay type"
                }
            ]
        },
        {
            "TableName": "ASSAYS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ASSAY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for the assay"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "DOC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to documents table"
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Description of the reported assay"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ASSAY_TYPE",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": None,
                    "Comment": "Assay classification, e.g. B=Binding assay, A=ADME assay, F=Functional assay"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_TEST_TYPE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Type of assay system (i.e., in vivo or in vitro)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_CATEGORY",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "screening, confirmatory (ie: dose-response), summary, panel, other,Thermal shift assay QC liability, Thermal shift assay, Affinity biochemical assay, Incucyte cell viability, Affinity phenotypic cellular assay, HTRF assay, Selectivity assay, Cell health data, NanoBRET assay, Alphascreen assay, Affinity on-target cellular assay, ITC assay, GPCR beta-arrestin recruitment assay"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_ORGANISM",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Name of the organism for the assay system (e.g., the organism, tissue or cell line in which an assay was performed). May differ from the target organism (e.g., for a human protein expressed in non-human cells, or pathogen-infected human cells)."
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI tax ID for the assay organism."
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_STRAIN",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Name of specific strain of the assay organism used (where known)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_TISSUE",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Name of tissue used in the assay system (e.g., for tissue-based assays) or from which the assay system was derived (e.g., for cell/subcellular fraction-based assays)."
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_CELL_TYPE",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Name of cell type or cell line used in the assay system (e.g., for cell-based assays)."
                },
                {
                    "Keys": None,
                    "ColumnName": "ASSAY_SUBCELLULAR_FRACTION",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Name of subcellular fraction used in the assay system (e.g., microsomes, mitochondria)."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Target identifier to which this assay has been mapped. Foreign key to target_dictionary. From ChEMBL_15 onwards, an assay will have only a single target assigned."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RELATIONSHIP_TYPE",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": None,
                    "Comment": "Flag indicating of the relationship between the reported target in the source document and the assigned target from TARGET_DICTIONARY. Foreign key to RELATIONSHIP_TYPE table."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "CONFIDENCE_SCORE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Confidence score, indicating how accurately the assigned target(s) represents the actually assay target. Foreign key to CONFIDENCE_SCORE table. 0 means uncurated/unassigned, 1 = low confidence to 9 = high confidence."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "CURATED_BY",
                    "DataType": "VARCHAR2(32)",
                    "Noneable": None,
                    "Comment": "Indicates the level of curation of the target assignment. Foreign key to curation_lookup table."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SRC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to source table"
                },
                {
                    "Keys": None,
                    "ColumnName": "SRC_ASSAY_ID",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Identifier for the assay in the source database/deposition (e.g., pubchem AID)"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier for this assay (for use on web interface etc)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "CELL_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to cell dictionary. The cell type or cell line used in the assay"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "BAO_FORMAT",
                    "DataType": "VARCHAR2(11)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding format type in BioAssay Ontology (e.g., cell-based, biochemical, organism-based etc)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "TISSUE_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "ID for the corresponding tissue/anatomy in Uberon. Foreign key to tissue_dictionary"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "VARIANT_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to variant_sequences table. Indicates the mutant/variant version of the target used in the assay (where known/applicable)"
                },
                {
                    "Keys": None,
                    "ColumnName": "AIDX",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "The Depositor Defined Assay Identifier"
                }
            ]
        },
        {
            "TableName": "ATC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": None,
                    "ColumnName": "WHO_NAME",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "WHO/INN name for the compound"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "First level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "Second level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "Third level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL4",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "Fourth level of classification"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "LEVEL5",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "Complete ATC code for compound"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of first level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of second level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of third level of classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL4_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of fourth level of classification"
                }
            ]
        },
        {
            "TableName": "BINDING_SITES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "SITE_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for a binding site in a given target."
                },
                {
                    "Keys": None,
                    "ColumnName": "SITE_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Name/label for the binding site."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to target_dictionary. Target on which the binding site is found."
                }
            ]
        },
        {
            "TableName": "BIO_COMPONENT_SEQUENCES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for each of the molecular components of biotherapeutics in ChEMBL (e.g., antibody chains, recombinant proteins, synthetic peptides)."
                },
                {
                    "Keys": None,
                    "ColumnName": "COMPONENT_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type of molecular component (e.g., 'PROTEIN', 'NUCLEIC ACID')."
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Description/name of molecular component."
                },
                {
                    "Keys": None,
                    "ColumnName": "SEQUENCE",
                    "DataType": "CLOB",
                    "Noneable": None,
                    "Comment": "Sequence of the biotherapeutic component."
                },
                {
                    "Keys": None,
                    "ColumnName": "SEQUENCE_MD5SUM",
                    "DataType": "VARCHAR2(32)",
                    "Noneable": None,
                    "Comment": "MD5 checksum of the sequence."
                },
                {
                    "Keys": None,
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI tax ID for the species from which the sequence is derived. May be None for humanized monoclonal antibodies, synthetic peptides etc."
                },
                {
                    "Keys": None,
                    "ColumnName": "ORGANISM",
                    "DataType": "VARCHAR2(150)",
                    "Noneable": None,
                    "Comment": "Name of the species from which the sequence is derived."
                }
            ]
        },
        {
            "TableName": "BIOASSAY_ONTOLOGY",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "BAO_ID",
                    "DataType": "VARCHAR2(11)",
                    "Noneable": "NOT None",
                    "Comment": "Bioassay Ontology identifier (BAO version 2.0)"
                },
                {
                    "Keys": None,
                    "ColumnName": "LABEL",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "Bioassay Ontology label for the term (BAO version 2.0)"
                }
            ]
        },
        {
            "TableName": "BIOTHERAPEUTIC_COMPONENTS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "BIOCOMP_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the biotherapeutics table, indicating which biotherapeutic the component is part of."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the bio_component_sequences table, indicating which component is part of the biotherapeutic."
                }
            ]
        },
        {
            "TableName": "BIOTHERAPEUTICS",
            "Columns": [
                {
                    "Keys": "PK,FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to molecule_dictionary"
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of the biotherapeutic."
                },
                {
                    "Keys": None,
                    "ColumnName": "HELM_NOTATION",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Sequence notation generated according to the HELM standard (http://www.openhelm.org/home). Currently for peptides only"
                }
            ]
        },
        {
            "TableName": "CELL_DICTIONARY",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CELL_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for each cell line in the target_dictionary."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "CELL_NAME",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Name of each cell line (as used in the target_dicitonary pref_name)."
                },
                {
                    "Keys": None,
                    "ColumnName": "CELL_DESCRIPTION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Longer description (where available) of the cell line."
                },
                {
                    "Keys": None,
                    "ColumnName": "CELL_SOURCE_TISSUE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Tissue from which the cell line is derived, where known."
                },
                {
                    "Keys": None,
                    "ColumnName": "CELL_SOURCE_ORGANISM",
                    "DataType": "VARCHAR2(150)",
                    "Noneable": None,
                    "Comment": "Name of organism from which the cell line is derived."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "CELL_SOURCE_TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI tax ID of the organism from which the cell line is derived."
                },
                {
                    "Keys": None,
                    "ColumnName": "CLO_ID",
                    "DataType": "VARCHAR2(11)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding cell line in Cell Line Ontology"
                },
                {
                    "Keys": None,
                    "ColumnName": "EFO_ID",
                    "DataType": "VARCHAR2(12)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding cell line in Experimental Factory Ontology"
                },
                {
                    "Keys": None,
                    "ColumnName": "CELLOSAURUS_ID",
                    "DataType": "VARCHAR2(15)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding cell line in Cellosaurus Ontology"
                },
                {
                    "Keys": None,
                    "ColumnName": "CL_LINCS_ID",
                    "DataType": "VARCHAR2(8)",
                    "Noneable": None,
                    "Comment": "Cell ID used in LINCS (Library of Integrated Network-based Cellular Signatures)"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "ChEMBL identifier for the cell (used in web interface etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "CELL_ONTOLOGY_ID",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "ID for the corresponding cell type in the Cell Ontology"
                }
            ]
        },
        {
            "TableName": "CHEMBL_ID_LOOKUP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ENTITY_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type of entity (e.g., COMPOUND, ASSAY, TARGET)"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ENTITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key for that entity in corresponding table (e.g., molregno for compounds, tid for targets)"
                },
                {
                    "Keys": None,
                    "ColumnName": "STATUS",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the status of the entity within the database - ACTIVE, INACTIVE (downgraded), OBS (obsolete/removed)."
                },
                {
                    "Keys": None,
                    "ColumnName": "LAST_ACTIVE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "indicates the last ChEMBL version where the CHEMBL_ID was active"
                }
            ]
        },
        {
            "TableName": "CHEMBL_RELEASE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CHEMBL_RELEASE_ID",
                    "DataType": "INTEGER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": None,
                    "ColumnName": "CHEMBL_RELEASE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "ChEMBL release name"
                },
                {
                    "Keys": None,
                    "ColumnName": "CREATION_DATE",
                    "DataType": "DATE",
                    "Noneable": None,
                    "Comment": "ChEMBL release creation date"
                }
            ]
        },
        {
            "TableName": "COMPONENT_CLASS",
            "Columns": [
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to component_sequences table."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "PROTEIN_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the protein_classification table."
                },
                {
                    "Keys": "PK",
                    "ColumnName": "COMP_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                }
            ]
        },
        {
            "TableName": "COMPONENT_DOMAINS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "COMPD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "DOMAIN_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the domains table, indicating the domain that is contained in the associated molecular component."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the component_sequences table, indicating the molecular_component that has the given domain."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "START_POSITION",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Start position of the domain within the sequence given in the component_sequences table."
                },
                {
                    "Keys": None,
                    "ColumnName": "END_POSITION",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "End position of the domain within the sequence given in the component_sequences table."
                }
            ]
        },
        {
            "TableName": "COMPONENT_GO",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "COMP_GO_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to COMPONENT_SEQUENCES table. The protein component this GO term applies to"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "GO_ID",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the GO_CLASSIFICATION table. The GO term that this protein is mapped to"
                }
            ]
        },
        {
            "TableName": "COMPONENT_SEQUENCES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for the component."
                },
                {
                    "Keys": None,
                    "ColumnName": "COMPONENT_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Type of molecular component represented (e.g., 'PROTEIN','DNA','RNA')."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ACCESSION",
                    "DataType": "VARCHAR2(25)",
                    "Noneable": None,
                    "Comment": "Accession for the sequence in the source database from which it was taken (e.g., UniProt accession for proteins)."
                },
                {
                    "Keys": None,
                    "ColumnName": "SEQUENCE",
                    "DataType": "CLOB",
                    "Noneable": None,
                    "Comment": "A representative sequence for the molecular component, as given in the source sequence database (not necessarily the exact sequence used in the assay)."
                },
                {
                    "Keys": None,
                    "ColumnName": "SEQUENCE_MD5SUM",
                    "DataType": "VARCHAR2(32)",
                    "Noneable": None,
                    "Comment": "MD5 checksum of the sequence."
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Description/name for the molecular component, usually taken from the source sequence database."
                },
                {
                    "Keys": None,
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI tax ID for the sequence in the source database (i.e., species that the protein/nucleic acid sequence comes from)."
                },
                {
                    "Keys": None,
                    "ColumnName": "ORGANISM",
                    "DataType": "VARCHAR2(150)",
                    "Noneable": None,
                    "Comment": "Name of the organism the sequence comes from."
                },
                {
                    "Keys": None,
                    "ColumnName": "DB_SOURCE",
                    "DataType": "VARCHAR2(25)",
                    "Noneable": None,
                    "Comment": "The name of the source sequence database from which sequences/accessions are taken. For UniProt proteins, this field indicates whether the sequence is from SWISS-PROT or TREMBL."
                },
                {
                    "Keys": None,
                    "ColumnName": "DB_VERSION",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "The version of the source sequence database from which sequences/accession were last updated."
                }
            ]
        },
        {
            "TableName": "COMPONENT_SYNONYMS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "COMPSYN_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the component_sequences table. The component to which this synonym applies."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "COMPONENT_SYNONYM",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "The synonym for the component."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SYN_TYPE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "The type or origin of the synonym (e.g., GENE_SYMBOL)."
                }
            ]
        },
        {
            "TableName": "COMPOUND_PROPERTIES",
            "Columns": [
                {
                    "Keys": "PK,FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to compounds table (compound structure)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MW_FREEBASE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Molecular weight of parent compound"
                },
                {
                    "Keys": None,
                    "ColumnName": "ALOGP",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Calculated ALogP"
                },
                {
                    "Keys": None,
                    "ColumnName": "HBA",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number hydrogen bond acceptors"
                },
                {
                    "Keys": None,
                    "ColumnName": "HBD",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number hydrogen bond donors"
                },
                {
                    "Keys": None,
                    "ColumnName": "PSA",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Polar surface area"
                },
                {
                    "Keys": None,
                    "ColumnName": "RTB",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number rotatable bonds"
                },
                {
                    "Keys": None,
                    "ColumnName": "RO3_PASS",
                    "DataType": "VARCHAR2(3)",
                    "Noneable": None,
                    "Comment": "Indicates whether the compound passes the rule-of-three (mw < 300, logP < 3 etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "NUM_RO5_VIOLATIONS",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of violations of Lipinski's rule-of-five, using HBA and HBD definitions"
                },
                {
                    "Keys": None,
                    "ColumnName": "CX_MOST_APKA",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The most acidic pKa calculated using ChemAxon v17.29.0"
                },
                {
                    "Keys": None,
                    "ColumnName": "CX_MOST_BPKA",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The most basic pKa calculated using ChemAxon v17.29.0"
                },
                {
                    "Keys": None,
                    "ColumnName": "CX_LOGP",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The calculated octanol/water partition coefficient using ChemAxon v17.29.0"
                },
                {
                    "Keys": None,
                    "ColumnName": "CX_LOGD",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The calculated octanol/water distribution coefficient at pH7.4 using ChemAxon v17.29.0"
                },
                {
                    "Keys": None,
                    "ColumnName": "MOLECULAR_SPECIES",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Indicates whether the compound is an acid/base/neutral"
                },
                {
                    "Keys": None,
                    "ColumnName": "FULL_MWT",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Molecular weight of the full compound including any salts"
                },
                {
                    "Keys": None,
                    "ColumnName": "AROMATIC_RINGS",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of aromatic rings"
                },
                {
                    "Keys": None,
                    "ColumnName": "HEAVY_ATOMS",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of heavy (non-hydrogen) atoms"
                },
                {
                    "Keys": None,
                    "ColumnName": "QED_WEIGHTED",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Weighted quantitative estimate of drug likeness (as defined by Bickerton et al., Nature Chem 2012)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MW_MONOISOTOPIC",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Monoisotopic parent molecular weight"
                },
                {
                    "Keys": None,
                    "ColumnName": "FULL_MOLFORMULA",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Molecular formula for the full compound (including any salt)"
                },
                {
                    "Keys": None,
                    "ColumnName": "HBA_LIPINSKI",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of hydrogen bond acceptors calculated according to Lipinski's original rules (i.e., N + O count))"
                },
                {
                    "Keys": None,
                    "ColumnName": "HBD_LIPINSKI",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of hydrogen bond donors calculated according to Lipinski's original rules (i.e., NH + OH count)"
                },
                {
                    "Keys": None,
                    "ColumnName": "NUM_LIPINSKI_RO5_VIOLATIONS",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Number of violations of Lipinski's rule of five using HBA_LIPINSKI and HBD_LIPINSKI counts"
                },
                {
                    "Keys": None,
                    "ColumnName": "NP_LIKENESS_SCORE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Natural Product-likeness Score: Peter Ertl, Silvio Roggo, and Ansgar Schuffenhauer Journal of Chemical Information and Modeling, 48, 68-74 (2008)"
                }
            ]
        },
        {
            "TableName": "COMPOUND_RECORDS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for a compound/record"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to compounds table (compound structure)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "DOC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to documents table"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMPOUND_KEY",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Key text identifying this compound in the scientific document"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMPOUND_NAME",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Name of this compound recorded in the scientific document"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SRC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to source table"
                },
                {
                    "Keys": None,
                    "ColumnName": "SRC_COMPOUND_ID",
                    "DataType": "VARCHAR2(150)",
                    "Noneable": None,
                    "Comment": "Identifier for the compound in the source database (e.g., pubchem SID)"
                },
                {
                    "Keys": None,
                    "ColumnName": "CIDX",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "The Depositor Defined Compound Identifier."
                }
            ]
        },
        {
            "TableName": "COMPOUND_STRUCTURAL_ALERTS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CPD_STR_ALERT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the molecule_dictionary. The compound for which the structural alert has been found."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ALERT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the structural_alerts table. The particular alert that has been identified in this compound."
                }
            ]
        },
        {
            "TableName": "COMPOUND_STRUCTURES",
            "Columns": [
                {
                    "Keys": "PK,FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Internal Primary Key for the compound structure and foreign key to molecule_dictionary table"
                },
                {
                    "Keys": None,
                    "ColumnName": "MOLFILE",
                    "DataType": "CLOB",
                    "Noneable": None,
                    "Comment": "MDL Connection table representation of compound"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "STANDARD_INCHI",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "IUPAC standard InChI for the compound"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "STANDARD_INCHI_KEY",
                    "DataType": "VARCHAR2(27)",
                    "Noneable": "NOT None",
                    "Comment": "IUPAC standard InChI key for the compound"
                },
                {
                    "Keys": None,
                    "ColumnName": "CANONICAL_SMILES",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Canonical smiles, generated using RDKit"
                }
            ]
        },
        {
            "TableName": "CONFIDENCE_SCORE_LOOKUP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CONFIDENCE_SCORE",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "0-9 score showing level of confidence in assignment of the precise molecular target of the assay"
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "Description of the target types assigned with each score"
                },
                {
                    "Keys": None,
                    "ColumnName": "TARGET_MAPPING",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "Short description of the target types assigned with each score"
                }
            ]
        },
        {
            "TableName": "CURATION_LOOKUP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CURATED_BY",
                    "DataType": "VARCHAR2(32)",
                    "Noneable": "NOT None",
                    "Comment": "Short description of the level of curation"
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "Definition of terms in the curated_by field."
                }
            ]
        },
        {
            "TableName": "DATA_VALIDITY_LOOKUP",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "DATA_VALIDITY_COMMENT",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Short description of various types of errors/warnings applied to values in the activities table."
                },
                {
                    "Keys": None,
                    "ColumnName": "DESCRIPTION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Definition of the terms in the data_validity_comment field."
                }
            ]
        },
        {
            "TableName": "DEFINED_DAILY_DOSE",
            "Columns": [
                {
                    "Keys": "FK",
                    "ColumnName": "ATC_CODE",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "ATC code for the compound (foreign key to ATC_CLASSIFICATION table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "DDD_UNITS",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Units of defined daily dose"
                },
                {
                    "Keys": None,
                    "ColumnName": "DDD_ADMR",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Administration route for dose"
                },
                {
                    "Keys": None,
                    "ColumnName": "DDD_COMMENT",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Comment"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "DDD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Internal primary key"
                },
                {
                    "Keys": None,
                    "ColumnName": "DDD_VALUE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Value of defined daily dose"
                }
            ]
        },
        {
            "TableName": "DOCS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "DOC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for the document"
                },
                {
                    "Keys": None,
                    "ColumnName": "JOURNAL",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Abbreviated journal name for an article"
                },
                {
                    "Keys": None,
                    "ColumnName": "YEAR",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Year of journal article publication"
                },
                {
                    "Keys": None,
                    "ColumnName": "VOLUME",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Volume of journal article"
                },
                {
                    "Keys": None,
                    "ColumnName": "ISSUE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Issue of journal article"
                },
                {
                    "Keys": None,
                    "ColumnName": "FIRST_PAGE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "First page number of journal article"
                },
                {
                    "Keys": None,
                    "ColumnName": "LAST_PAGE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Last page number of journal article"
                },
                {
                    "Keys": None,
                    "ColumnName": "PUBMED_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NIH pubmed record ID, where available"
                },
                {
                    "Keys": None,
                    "ColumnName": "DOI",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Digital object identifier for this reference"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier for this document (for use on web interface etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "TITLE",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "Document title (e.g., Publication title or description of dataset)"
                },
                {
                    "Keys": None,
                    "ColumnName": "DOC_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type of the document (e.g., Publication, Deposited dataset)"
                },
                {
                    "Keys": None,
                    "ColumnName": "AUTHORS",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "For a deposited dataset, the authors carrying out the screening and/or submitting the dataset."
                },
                {
                    "Keys": None,
                    "ColumnName": "ABSTRACT",
                    "DataType": "CLOB",
                    "Noneable": None,
                    "Comment": "For a deposited dataset, a brief description of the dataset."
                },
                {
                    "Keys": None,
                    "ColumnName": "PATENT_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Patent ID for this document"
                },
                {
                    "Keys": None,
                    "ColumnName": "RIDX",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "The Depositor Defined Reference Identifier"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SRC_ID",
                    "DataType": "INTEGER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to Source table, indicating the source of this document"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "CHEMBL_RELEASE_ID",
                    "DataType": "INTEGER",
                    "Noneable": None,
                    "Comment": "Foreign key to chembl_release table"
                },
                {
                    "Keys": None,
                    "ColumnName": "CONTACT",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Details of someone willing to be contacted over the dataset (ideally ORCID ID, up to 3)"
                }
            ]
        },
        {
            "TableName": "DOMAINS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "DOMAIN_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for each domain."
                },
                {
                    "Keys": None,
                    "ColumnName": "DOMAIN_TYPE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "Indicates the source of the domain (e.g., Pfam)."
                },
                {
                    "Keys": None,
                    "ColumnName": "SOURCE_DOMAIN_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "Identifier for the domain in the source database (e.g., Pfam ID such as PF00001)."
                },
                {
                    "Keys": None,
                    "ColumnName": "DOMAIN_NAME",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Name given to the domain in the source database (e.g., 7tm_1)."
                },
                {
                    "Keys": None,
                    "ColumnName": "DOMAIN_DESCRIPTION",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "Longer name or description for the domain."
                }
            ]
        },
        {
            "TableName": "DRUG_INDICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "DRUGIND_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to compound_records table. Links to the drug record to which this indication applies"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Molregno for the drug (foreign key to the molecule_dictionary and compound_records tables)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MAX_PHASE_FOR_IND",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Maximum phase of development that the drug is known to have reached for this particular indication (4 = Approved, 3 = Phase 3 Clinical Trials, 2 = Phase 2 Clinical Trials, 1 = Phase 1 Clinical Trials, 0.5 = Early Phase 1 Clinical Trials, -1 = Clinical Phase unknown for drug or clinical candidate drug ie where ChEMBL cannot assign a clinical phase)"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "MESH_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "Medical Subject Headings (MeSH) disease identifier corresponding to the indication"
                },
                {
                    "Keys": None,
                    "ColumnName": "MESH_HEADING",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "Medical Subject Heading term for the MeSH disease ID"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "EFO_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Experimental Factor Ontology (EFO) disease identifier corresponding to the indication"
                },
                {
                    "Keys": None,
                    "ColumnName": "EFO_TERM",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Experimental Factor Ontology term for the EFO ID"
                }
            ]
        },
        {
            "TableName": "DRUG_MECHANISM",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MEC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key for each drug mechanism of action"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Record_id for the drug (foreign key to compound_records table)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Molregno for the drug (foreign key to molecule_dictionary table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MECHANISM_OF_ACTION",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Description of the mechanism of action e.g., 'Phosphodiesterase 5 inhibitor'"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Target associated with this mechanism of action (foreign key to target_dictionary table)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SITE_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Binding site for the drug within the target (where known) - foreign key to binding_sites table"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ACTION_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Type of action of the drug on the target e.g., agonist/antagonist etc (foreign key to action_type table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "DIRECT_INTERACTION",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether the molecule is believed to interact directly with the target (1 = yes, 0 = no)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MOLECULAR_MECHANISM",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether the mechanism of action describes the molecular target of the drug, rather than a higher-level physiological mechanism e.g., vasodilator (1 = yes, 0 = no)"
                },
                {
                    "Keys": None,
                    "ColumnName": "DISEASE_EFFICACY",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether the target assigned is believed to play a role in the efficacy of the drug in the indication(s) for which it is approved (1 = yes, 0 = no)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MECHANISM_COMMENT",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Additional comments regarding the mechanism of action"
                },
                {
                    "Keys": None,
                    "ColumnName": "SELECTIVITY_COMMENT",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Additional comments regarding the selectivity of the drug"
                },
                {
                    "Keys": None,
                    "ColumnName": "BINDING_SITE_COMMENT",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Additional comments regarding the binding site of the drug"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "VARIANT_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to variant_sequences table. Indicates the mutant/variant version of the target used in the assay (where known/applicable)"
                }
            ]
        },
        {
            "TableName": "DRUG_WARNING",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "WARNING_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key for the drug warning"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the compound_records table"
                },
                {
                    "Keys": None,
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to molecule_dictionary table"
                },
                {
                    "Keys": None,
                    "ColumnName": "WARNING_TYPE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Description of the drug warning type (e.g., withdrawn vs black box warning)"
                },
                {
                    "Keys": None,
                    "ColumnName": "WARNING_CLASS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "High-level class of the drug warning"
                },
                {
                    "Keys": None,
                    "ColumnName": "WARNING_DESCRIPTION",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Description of the drug warning"
                },
                {
                    "Keys": None,
                    "ColumnName": "WARNING_COUNTRY",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "List of countries/regions associated with the drug warning"
                },
                {
                    "Keys": None,
                    "ColumnName": "WARNING_YEAR",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Earliest year the warning was applied to the drug."
                },
                {
                    "Keys": None,
                    "ColumnName": "EFO_TERM",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Term for Experimental Factor Ontology (EFO)"
                },
                {
                    "Keys": None,
                    "ColumnName": "EFO_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Identifier for Experimental Factor Ontology (EFO)"
                },
                {
                    "Keys": None,
                    "ColumnName": "EFO_ID_FOR_WARNING_CLASS",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Warning Class Identifier for Experimental Factor Ontology (EFO)"
                }
            ]
        },
        {
            "TableName": "FORMULATIONS",
            "Columns": [
                {
                    "Keys": "FK,UK",
                    "ColumnName": "PRODUCT_ID",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "Unique identifier of the product. FK to PRODUCTS"
                },
                {
                    "Keys": None,
                    "ColumnName": "INGREDIENT",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Name of the approved ingredient within the product"
                },
                {
                    "Keys": None,
                    "ColumnName": "STRENGTH",
                    "DataType": "VARCHAR2(300)",
                    "Noneable": None,
                    "Comment": "Dose strength"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the compound_records table."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Unique identifier of the ingredient FK to MOLECULE_DICTIONARY"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "FORMULATION_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                }
            ]
        },
        {
            "TableName": "FRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "FRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique numeric primary key for each level5 code"
                },
                {
                    "Keys": None,
                    "ColumnName": "ACTIVE_INGREDIENT",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": "NOT None",
                    "Comment": "Name of active ingredient (fungicide) classified by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1",
                    "DataType": "VARCHAR2(2)",
                    "Noneable": "NOT None",
                    "Comment": "Mechanism of action code assigned by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": "NOT None",
                    "Comment": "Description of mechanism of action"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2",
                    "DataType": "VARCHAR2(2)",
                    "Noneable": "NOT None",
                    "Comment": "Target site code assigned by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of target provided by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3",
                    "DataType": "VARCHAR2(6)",
                    "Noneable": "NOT None",
                    "Comment": "Group number assigned by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of group provided by FRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL4",
                    "DataType": "VARCHAR2(7)",
                    "Noneable": "NOT None",
                    "Comment": "Number denoting the chemical group (number not assigned by FRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL4_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Chemical group name provided by FRAC"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "LEVEL5",
                    "DataType": "VARCHAR2(8)",
                    "Noneable": "NOT None",
                    "Comment": "A unique code assigned to each ingredient (based on the level 1-4 FRAC classification, but not assigned by IRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "FRAC_CODE",
                    "DataType": "VARCHAR2(4)",
                    "Noneable": "NOT None",
                    "Comment": "The official FRAC classification code for the ingredient"
                }
            ]
        },
        {
            "TableName": "GO_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "GO_ID",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Gene Ontology identifier for the GO slim term"
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENT_GO_ID",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "Gene Ontology identifier for the parent of this GO term in the ChEMBL Drug Target GO slim"
                },
                {
                    "Keys": None,
                    "ColumnName": "PREF_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Gene Ontology name"
                },
                {
                    "Keys": None,
                    "ColumnName": "CLASS_LEVEL",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Indicates the level of the term in the slim (L1 = highest)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ASPECT",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": None,
                    "Comment": "Indicates which aspect of the Gene Ontology the term belongs to (F = molecular function, P = biological process, C = cellular component)"
                },
                {
                    "Keys": None,
                    "ColumnName": "PATH",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Indicates the full path to this term in the GO slim"
                }
            ]
        },
        {
            "TableName": "HRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "HRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique numeric primary key for each level3 code"
                },
                {
                    "Keys": None,
                    "ColumnName": "ACTIVE_INGREDIENT",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": "NOT None",
                    "Comment": "Name of active ingredient (herbicide) classified by HRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1",
                    "DataType": "VARCHAR2(2)",
                    "Noneable": "NOT None",
                    "Comment": "HRAC group code - denoting mechanism of action of herbicide"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": "NOT None",
                    "Comment": "Description of mechanism of action provided by HRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2",
                    "DataType": "VARCHAR2(3)",
                    "Noneable": "NOT None",
                    "Comment": "Indicates a chemical family within a particular HRAC group (number not assigned by HRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of chemical family provided by HRAC"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "LEVEL3",
                    "DataType": "VARCHAR2(5)",
                    "Noneable": "NOT None",
                    "Comment": "A unique code assigned to each ingredient (based on the level 1 and 2 HRAC classification, but not assigned by HRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "HRAC_CODE",
                    "DataType": "VARCHAR2(2)",
                    "Noneable": "NOT None",
                    "Comment": "The official HRAC classification code for the ingredient"
                }
            ]
        },
        {
            "TableName": "INDICATION_REFS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "INDREF_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "DRUGIND_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the DRUG_INDICATION table, indicating the drug-indication link that this reference applies to"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type/source of reference"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_ID",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": "NOT None",
                    "Comment": "Identifier for the reference in the source"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_URL",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": "NOT None",
                    "Comment": "Full URL linking to the reference"
                }
            ]
        },
        {
            "TableName": "IRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "IRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique numeric primary key for each level4 code"
                },
                {
                    "Keys": None,
                    "ColumnName": "ACTIVE_INGREDIENT",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": "NOT None",
                    "Comment": "Name of active ingredient (insecticide) classified by IRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": "NOT None",
                    "Comment": "Class of action e.g., nerve action, energy metabolism (code not assigned by IRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL1_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": "NOT None",
                    "Comment": "Description of class of action, as provided by IRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2",
                    "DataType": "VARCHAR2(3)",
                    "Noneable": "NOT None",
                    "Comment": "IRAC main group code denoting primary site/mechanism of action"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL2_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": "NOT None",
                    "Comment": "Description of site/mechanism of action provided by IRAC"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3",
                    "DataType": "VARCHAR2(6)",
                    "Noneable": "NOT None",
                    "Comment": "IRAC sub-group code denoting chemical class of insecticide"
                },
                {
                    "Keys": None,
                    "ColumnName": "LEVEL3_DESCRIPTION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": "NOT None",
                    "Comment": "Description of chemical class or exemplifying ingredient provided by IRAC"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "LEVEL4",
                    "DataType": "VARCHAR2(8)",
                    "Noneable": "NOT None",
                    "Comment": "A unique code assigned to each ingredient (based on the level 1, 2 and 3 IRAC classification, but not assigned by IRAC)"
                },
                {
                    "Keys": None,
                    "ColumnName": "IRAC_CODE",
                    "DataType": "VARCHAR2(3)",
                    "Noneable": "NOT None",
                    "Comment": "The official IRAC classification code for the ingredient"
                }
            ]
        },
        {
            "TableName": "LIGAND_EFF",
            "Columns": [
                {
                    "Keys": "PK,FK",
                    "ColumnName": "ACTIVITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Link key to activities table"
                },
                {
                    "Keys": None,
                    "ColumnName": "BEI",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Binding Efficiency Index = p(XC50) *1000/MW_freebase"
                },
                {
                    "Keys": None,
                    "ColumnName": "SEI",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Surface Efficiency Index = p(XC50)*100/PSA"
                },
                {
                    "Keys": None,
                    "ColumnName": "LE",
                    "DataType": "NUMBER",
                    "Noneable": "Ligand Efficiency = deltaG/heavy_atoms",
                    "Comment": "[from the Hopkins DDT paper 2004]"
                },
                {
                    "Keys": None,
                    "ColumnName": "LLE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Lipophilic Ligand Efficiency = -logKi-ALogP. [from Leeson NRDD 2007]"
                }
            ]
        },
        {
            "TableName": "MECHANISM_REFS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MECREF_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MEC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to drug_mechanism table - indicating the mechanism to which the references refer"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type/source of reference (e.g., 'PubMed','DailyMed')"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_ID",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Identifier for the reference in the source (e.g., PubMed ID or DailyMed setid)"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_URL",
                    "DataType": "VARCHAR2(400)",
                    "Noneable": None,
                    "Comment": "Full URL linking to the reference"
                }
            ]
        },
        {
            "TableName": "METABOLISM",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MET_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "DRUG_RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to compound_records. Record representing the drug or other compound for which metabolism is being studied (may not be the same as the substrate being measured)"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "SUBSTRATE_RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to compound_records. Record representing the compound that is the subject of metabolism"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "METABOLITE_RECORD_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to compound_records. Record representing the compound that is the result of metabolism"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "PATHWAY_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Identifier for the metabolic scheme/pathway (may be multiple pathways from one source document)"
                },
                {
                    "Keys": None,
                    "ColumnName": "PATHWAY_KEY",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Link to original source indicating where the pathway information was found (e.g., Figure 1, page 23)"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ENZYME_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Name of the enzyme responsible for the metabolic conversion"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ENZYME_TID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to target_dictionary. TID for the enzyme responsible for the metabolic conversion"
                },
                {
                    "Keys": None,
                    "ColumnName": "MET_CONVERSION",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Description of the metabolic conversion"
                },
                {
                    "Keys": None,
                    "ColumnName": "ORGANISM",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Organism in which this metabolic reaction occurs"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI Tax ID for the organism in which this metabolic reaction occurs"
                },
                {
                    "Keys": None,
                    "ColumnName": "MET_COMMENT",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Additional information regarding the metabolism (e.g., organ system, conditions under which observed, activity of metabolites)"
                }
            ]
        },
        {
            "TableName": "METABOLISM_REFS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "METREF_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MET_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to record_metabolism table - indicating the metabolism information to which the references refer"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type/source of reference (e.g., 'PubMed','DailyMed')"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "REF_ID",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Identifier for the reference in the source (e.g., PubMed ID or DailyMed setid)"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_URL",
                    "DataType": "VARCHAR2(400)",
                    "Noneable": None,
                    "Comment": "Full URL linking to the reference"
                }
            ]
        },
        {
            "TableName": "MOLECULE_ATC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MOL_ATC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "LEVEL5",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "ATC code (foreign key to atc_classification table)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Drug to which the ATC code applies (foreign key to molecule_dictionary table)"
                }
            ]
        },
        {
            "TableName": "MOLECULE_DICTIONARY",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Internal Primary Key for the molecule"
                },
                {
                    "Keys": None,
                    "ColumnName": "PREF_NAME",
                    "DataType": "VARCHAR2(255)",
                    "Noneable": None,
                    "Comment": "Preferred name for the molecule"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier for this compound (for use on web interface etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "MAX_PHASE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Maximum phase of development reached for the compound across all indications (4 = Approved, 3 = Phase 3 Clinical Trials, 2 = Phase 2 Clinical Trials, 1 = Phase 1 Clinical Trials, 0.5 = Early Phase 1 Clinical Trials, -1 = Clinical Phase unknown for drug or clinical candidate drug ie where ChEMBL cannot assign a clinical phase, None = preclinical compounds with bioactivity data)"
                },
                {
                    "Keys": None,
                    "ColumnName": "THERAPEUTIC_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates that a drug has a therapeutic application, as opposed to e.g., an imaging agent, additive etc (1 = yes, 0 = default value)."
                },
                {
                    "Keys": None,
                    "ColumnName": "DOSED_INGREDIENT",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates that the drug is dosed in this form, e.g., a particular salt (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "STRUCTURE_TYPE",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the molecule has a small molecule structure or a protein sequence (MOL indicates an entry in the compound_structures table, SEQ indications an entry in the protein_therapeutics table, NONE indicates an entry in neither table, e.g., structure unknown)"
                },
                {
                    "Keys": None,
                    "ColumnName": "CHEBI_PAR_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Preferred ChEBI ID for the compound (where different from assigned). TO BE DEPRECATED - please use UniChem (https://www.ebi.ac.uk/unichem/)."
                },
                {
                    "Keys": None,
                    "ColumnName": "MOLECULE_TYPE",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": None,
                    "Comment": "Type of molecule (Small molecule, Protein, Antibody, Antibody drug conjugate, Oligosaccharide, Oligonucleotide, Cell, Enzyme, Gene, Unknown)"
                },
                {
                    "Keys": None,
                    "ColumnName": "FIRST_APPROVAL",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Earliest known approval year for the drug (None is the default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ORAL",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the drug is known to be administered orally (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENTERAL",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the drug is known to be administered parenterally (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "TOPICAL",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the drug is known to be administered topically (1 = yes, 0 = default value)."
                },
                {
                    "Keys": None,
                    "ColumnName": "BLACK_BOX_WARNING",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates that the drug has a black box warning (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "NATURAL_PRODUCT",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the compound is a natural product as defined by COCONUT (https://coconut.naturalproducts.net/), the COlleCtion of Open Natural ProdUcTs. (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "FIRST_IN_CLASS",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether this is known to be the first approved drug of its class (e.g., acting on a particular target). This is regardless of the indication, or the route of administration (1 = yes, 0 = no, -1 = preclinical compound ie not a drug)."
                },
                {
                    "Keys": None,
                    "ColumnName": "CHIRALITY",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Shows whether a drug is dosed as a racemic mixture (0), single stereoisomer (1), an achiral molecule (2), or has unknown chirality (-1)"
                },
                {
                    "Keys": None,
                    "ColumnName": "PRODRUG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates that the drug is a pro-drug. See active_molregno field in molecule hierarchy for the pharmacologically active molecule, where known (1 = yes, 0 = no, -1 = preclinical compound ie not a drug)"
                },
                {
                    "Keys": None,
                    "ColumnName": "INORGANIC_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the molecule is inorganic i.e., containing only metal atoms and <2 carbon atoms (1 = yes, 0 = no, -1 = preclinical compound ie not a drug)"
                },
                {
                    "Keys": None,
                    "ColumnName": "USAN_YEAR",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The year in which the application for a USAN/INN name was granted. (None is the default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "AVAILABILITY_TYPE",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "The availability type for the drug (-2 = withdrawn, -1 = unknown, 0 = discontinued, 1 = prescription only, 2 = over the counter)"
                },
                {
                    "Keys": None,
                    "ColumnName": "USAN_STEM",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Where the drug or clinical candidate name can be matched, this indicates the USAN stem (None is the default value). Also described in the USAN_STEMS table."
                },
                {
                    "Keys": None,
                    "ColumnName": "POLYMER_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Indicates whether a molecule is a small molecule polymer, e.g., polistyrex (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "USAN_SUBSTEM",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Where the drug or clinical candidate name can be matched, this indicates the USAN substem (None is the default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "USAN_STEM_DEFINITION",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Definition of the USAN stem (None is the default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "INDICATION_CLASS",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "Indication class(es) assigned to a drug in the USP dictionary. TO BE DEPRECATED - please use DRUG_INDICATION table."
                },
                {
                    "Keys": None,
                    "ColumnName": "WITHDRAWN_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates an approved drug has been withdrawn for toxicity reasons for all indications, for all populations at all doses in at least one country (not necessarily in the US). (1 = yes, 0 = default value)"
                },
                {
                    "Keys": None,
                    "ColumnName": "CHEMICAL_PROBE",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates whether the compound is a chemical probe; for exact definition see release notes (1 = yes, 0 = default value)."
                },
                {
                    "Keys": None,
                    "ColumnName": "ORPHAN",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates orphan designation, i.e. intended for use against a rare condition (1 = yes, 0 = no, -1 = preclinical compound ie not a drug)"
                }
            ]
        },
        {
            "TableName": "MOLECULE_FRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MOL_FRAC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "FRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to frac_classification table showing the mechanism of action classification of the compound."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to molecule_dictionary, showing the compound to which the classification applies."
                }
            ]
        },
        {
            "TableName": "MOLECULE_HIERARCHY",
            "Columns": [
                {
                    "Keys": "PK,FK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to compounds table. This field holds a list of all of the ChEMBL compounds with associated data (e.g., activity information, approved drugs). Parent compounds that are generated only by removing salts, and which do not themselves have any associated data will not appear here."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "PARENT_MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Represents parent compound of molregno in first field (i.e., generated by removing salts). Where molregno and parent_molregno are same, the initial ChEMBL compound did not contain a salt component, or else could not be further processed for various reasons (e.g., inorganic mixture). Compounds which are only generated by removing salts will appear in this field only. Those which, themselves, have any associated data (e.g., activity data) or are launched drugs will also appear in the molregno field."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ACTIVE_MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Where a compound is a pro-drug, this represents the active metabolite of the 'dosed' compound given by parent_molregno. Where parent_molregno and active_molregno are the same, the compound is not currently known to be a pro-drug."
                }
            ]
        },
        {
            "TableName": "MOLECULE_HRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MOL_HRAC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "HRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to hrac_classification table showing the classification for the compound."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to molecule_dictionary, showing the compound to which this classification applies."
                }
            ]
        },
        {
            "TableName": "MOLECULE_IRAC_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "MOL_IRAC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "IRAC_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the irac_classification table showing the mechanism of action classification for the compound."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the molecule_dictionary table, showing the compound to which the classification applies."
                }
            ]
        },
        {
            "TableName": "MOLECULE_SYNONYMS",
            "Columns": [
                {
                    "Keys": "FK,UK",
                    "ColumnName": "MOLREGNO",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to molecule_dictionary"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SYN_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Type of name/synonym (e.g., TRADE_NAME, RESEARCH_CODE, USAN)"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "MOLSYN_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RES_STEM_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the research_stem table. Where a synonym is a research code, this links to further information about the company associated with that code. TO BE DEPRECATED."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SYNONYMS",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Synonym for the compound"
                }
            ]
        },
        {
            "TableName": "ORGANISM_CLASS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "OC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Internal primary key"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI taxonomy ID for the organism (corresponding to tax_ids in target_dictionary table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "L1",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Highest level classification (e.g., Eukaryotes, Bacteria, Fungi etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "L2",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Second level classification"
                },
                {
                    "Keys": None,
                    "ColumnName": "L3",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Third level classification"
                }
            ]
        },
        {
            "TableName": "PATENT_USE_CODES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "PATENT_USE_CODE",
                    "DataType": "VARCHAR2(8)",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Patent use code from FDA Orange Book"
                },
                {
                    "Keys": None,
                    "ColumnName": "DEFINITION",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": "NOT None",
                    "Comment": "Definition for the patent use code, from FDA Orange Book."
                }
            ]
        },
        {
            "TableName": "PREDICTED_BINDING_DOMAINS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "PREDBIND_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "ACTIVITY_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the activities table, indicating the compound/assay(+target) combination for which this prediction is made."
                },
                {
                    "Keys": "FK",
                    "ColumnName": "SITE_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the binding_sites table, indicating the binding site (domain) that the compound is predicted to bind to."
                },
                {
                    "Keys": None,
                    "ColumnName": "PREDICTION_METHOD",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "The method used to assign the binding domain (e.g., 'Single domain' where the protein has only 1 domain, 'Multi domain' where the protein has multiple domains, but only 1 is known to bind small molecules in other proteins)."
                },
                {
                    "Keys": None,
                    "ColumnName": "CONFIDENCE",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "The level of confidence assigned to the prediction (high where the protein has only 1 domain, medium where the compound has multiple domains, but only 1 known small molecule-binding domain)."
                }
            ]
        },
        {
            "TableName": "PRODUCT_PATENTS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "PROD_PAT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "PRODUCT_ID",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to products table - FDA application number for the product"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "PATENT_NO",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "Patent numbers as submitted by the applicant holder for patents covered by the statutory provisions"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "PATENT_EXPIRE_DATE",
                    "DataType": "DATE",
                    "Noneable": "NOT None",
                    "Comment": "Date the patent expires as submitted by the applicant holder including applicable extensions"
                },
                {
                    "Keys": None,
                    "ColumnName": "DRUG_SUBSTANCE_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Patents submitted on FDA Form 3542 and listed after August 18, 2003 may have a drug substance flag set to 1, indicating the sponsor submitted the patent as claiming the drug substance"
                },
                {
                    "Keys": None,
                    "ColumnName": "DRUG_PRODUCT_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Patents submitted on FDA Form 3542 and listed after August 18, 2003 may have a drug product flag set to 1, indicating the sponsor submitted the patent as claiming the drug product"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "PATENT_USE_CODE",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": None,
                    "Comment": "Code to designate a use patent that covers the approved indication or use of a drug product"
                },
                {
                    "Keys": None,
                    "ColumnName": "DELIST_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Sponsor has requested patent be delisted if set to 1."
                },
                {
                    "Keys": None,
                    "ColumnName": "SUBMISSION_DATE",
                    "DataType": "DATE",
                    "Noneable": None,
                    "Comment": "The date on which the FDA receives patent information from the new drug application (NDA) holder. Format is Mmm d, yyyy"
                }
            ]
        },
        {
            "TableName": "PRODUCTS",
            "Columns": [
                {
                    "Keys": None,
                    "ColumnName": "DOSAGE_FORM",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "The dosage form of the product (e.g., tablet, capsule etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "ROUTE",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "The administration route of the product (e.g., oral, injection etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "TRADE_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "The trade name for the product"
                },
                {
                    "Keys": None,
                    "ColumnName": "APPROVAL_DATE",
                    "DataType": "DATE",
                    "Noneable": None,
                    "Comment": "The FDA approval date for the product (not necessarily first approval of the active ingredient)"
                },
                {
                    "Keys": None,
                    "ColumnName": "AD_TYPE",
                    "DataType": "VARCHAR2(5)",
                    "Noneable": None,
                    "Comment": "RX = prescription, OTC = over the counter, DISCN = discontinued"
                },
                {
                    "Keys": None,
                    "ColumnName": "ORAL",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether product is orally delivered"
                },
                {
                    "Keys": None,
                    "ColumnName": "TOPICAL",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether product is topically delivered"
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENTERAL",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether product is parenterally delivered"
                },
                {
                    "Keys": None,
                    "ColumnName": "BLACK_BOX_WARNING",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether the product label has a black box warning"
                },
                {
                    "Keys": None,
                    "ColumnName": "APPLICANT_FULL_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Name of the company applying for FDA approval"
                },
                {
                    "Keys": None,
                    "ColumnName": "INNOVATOR_COMPANY",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Flag to show whether the applicant is the innovator of the product"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "PRODUCT_ID",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "FDA application number for the product"
                },
                {
                    "Keys": None,
                    "ColumnName": "NDA_TYPE",
                    "DataType": "VARCHAR2(10)",
                    "Noneable": "New Drug Application Type. The type of new drug application approval.",
                    "Comment": "New Drug Applications (NDA or innovator)"
                }
            ]
        },
        {
            "TableName": "PROTEIN_CLASS_SYNONYMS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "PROTCLASSSYN_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "PROTEIN_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the PROTEIN_CLASSIFICATION table. The protein_class to which this synonym applies."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "PROTEIN_CLASS_SYNONYM",
                    "DataType": "VARCHAR2(1000)",
                    "Noneable": None,
                    "Comment": "The synonym for the protein class."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SYN_TYPE",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "The type or origin of the synonym (e.g., ChEMBL, Concept Wiki, UMLS)."
                }
            ]
        },
        {
            "TableName": "PROTEIN_CLASSIFICATION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "PROTEIN_CLASS_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for each protein family classification."
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Protein_class_id for the parent of this protein family."
                },
                {
                    "Keys": None,
                    "ColumnName": "PREF_NAME",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "Preferred/full name for this protein family."
                },
                {
                    "Keys": None,
                    "ColumnName": "SHORT_NAME",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Short/abbreviated name for this protein family (not necessarily unique)."
                },
                {
                    "Keys": None,
                    "ColumnName": "PROTEIN_CLASS_DESC",
                    "DataType": "VARCHAR2(410)",
                    "Noneable": "NOT None",
                    "Comment": "Concatenated description of each classification for searching purposes etc."
                },
                {
                    "Keys": None,
                    "ColumnName": "DEFINITION",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Definition of the protein family."
                },
                {
                    "Keys": None,
                    "ColumnName": "CLASS_LEVEL",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Level of the class within the hierarchy (level 1 = top level classification)"
                }
            ]
        },
        {
            "TableName": "RELATIONSHIP_TYPE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "RELATIONSHIP_TYPE",
                    "DataType": "VARCHAR2(1)",
                    "Noneable": "NOT None",
                    "Comment": "Relationship_type flag used in the assays table"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATIONSHIP_DESC",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Description of relationship_type flags"
                }
            ]
        },
        {
            "TableName": "RESEARCH_COMPANIES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "CO_STEM_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "RES_STEM_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to research_stem table. TO BE DEPRECATED."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "COMPANY",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Name of current company associated with this research code stem. TO BE DEPRECATED."
                },
                {
                    "Keys": None,
                    "ColumnName": "COUNTRY",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Country in which the company uses this research code stem. TO BE DEPRECATED."
                },
                {
                    "Keys": None,
                    "ColumnName": "PREVIOUS_COMPANY",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Previous name of the company associated with this research code stem (e.g., if the company has undergone acquisitions/mergers). TO BE DEPRECATED."
                }
            ]
        },
        {
            "TableName": "RESEARCH_STEM",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "RES_STEM_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique ID for each research code stem. TO BE DEPRECATED."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "RESEARCH_STEM",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "The actual stem/prefix used in the research code. TO BE DEPRECATED."
                }
            ]
        },
        {
            "TableName": "SITE_COMPONENTS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "SITECOMP_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "SITE_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to binding_sites table."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the component_sequences table, indicating which molecular component of the target is involved in the binding site."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "DOMAIN_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the domains table, indicating which domain of the given molecular component is involved in the binding site (where not known, the domain_id may be None)."
                },
                {
                    "Keys": None,
                    "ColumnName": "SITE_RESIDUES",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "List of residues from the given molecular component that make up the binding site (where not know, will be None)."
                }
            ]
        },
        {
            "TableName": "SOURCE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "SRC_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Identifier for each source (used in compound_records and assays tables)"
                },
                {
                    "Keys": None,
                    "ColumnName": "SRC_DESCRIPTION",
                    "DataType": "VARCHAR2(500)",
                    "Noneable": None,
                    "Comment": "Description of the data source"
                },
                {
                    "Keys": None,
                    "ColumnName": "SRC_SHORT_NAME",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "A short name for each data source, for display purposes"
                }
            ]
        },
        {
            "TableName": "STRUCTURAL_ALERT_SETS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ALERT_SET_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for the structural alert set"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SET_NAME",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "Name (or origin) of the structural alert set"
                },
                {
                    "Keys": None,
                    "ColumnName": "PRIORITY",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Priority assigned to the structural alert set for display on the ChEMBL interface (priorities >=4 are shown by default)."
                }
            ]
        },
        {
            "TableName": "STRUCTURAL_ALERTS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "ALERT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key. Unique identifier for the structural alert"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "ALERT_SET_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to structural_alert_sets table indicating which set this particular alert comes from"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ALERT_NAME",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "A name for the structural alert"
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SMARTS",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": "NOT None",
                    "Comment": "SMARTS defining the structural feature that is considered to be an alert"
                }
            ]
        },
        {
            "TableName": "TARGET_COMPONENTS",
            "Columns": [
                {
                    "Keys": "FK,UK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the target_dictionary, indicating the target to which the components belong."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "COMPONENT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Foreign key to the component_sequences table, indicating which components belong to the target."
                },
                {
                    "Keys": "PK",
                    "ColumnName": "TARGCOMP_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key."
                },
                {
                    "Keys": None,
                    "ColumnName": "HOMOLOGUE",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Indicates that the given component is a homologue of the correct component (e.g., from a different species) when set to 1. This may be the case if the sequence for the correct protein/nucleic acid cannot be found in sequence databases. A value of 2 indicates that the sequence given is a representative of a species group, e.g., an E. coli protein to represent the target of a broad-spectrum antibiotic."
                }
            ]
        },
        {
            "TableName": "TARGET_DICTIONARY",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Unique ID for the target"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "TARGET_TYPE",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": None,
                    "Comment": "Describes whether target is a protein, an organism, a tissue etc. Foreign key to TARGET_TYPE table."
                },
                {
                    "Keys": None,
                    "ColumnName": "PREF_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "Preferred target name: manually curated"
                },
                {
                    "Keys": None,
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI taxonomy id of target"
                },
                {
                    "Keys": None,
                    "ColumnName": "ORGANISM",
                    "DataType": "VARCHAR2(150)",
                    "Noneable": None,
                    "Comment": "Source organism of molecuar target or tissue, or the target organism if compound activity is reported in an organism rather than a protein or tissue"
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier for this target (for use on web interface etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "SPECIES_GROUP_FLAG",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Flag to indicate whether the target represents a group of species, rather than an individual species (e.g., 'Bacterial DHFR'). Where set to 1, indicates that any associated target components will be a representative, rather than a comprehensive set."
                }
            ]
        },
        {
            "TableName": "TARGET_RELATIONS",
            "Columns": [
                {
                    "Keys": "FK",
                    "ColumnName": "TID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Identifier for target of interest (foreign key to target_dictionary table)"
                },
                {
                    "Keys": None,
                    "ColumnName": "RELATIONSHIP",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "Relationship between two targets (e.g., SUBSET OF, SUPERSET OF, OVERLAPS WITH)"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "RELATED_TID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Identifier for the target that is related to the target of interest (foreign key to target_dicitionary table)"
                },
                {
                    "Keys": "PK",
                    "ColumnName": "TARGREL_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key"
                }
            ]
        },
        {
            "TableName": "TARGET_TYPE",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "TARGET_TYPE",
                    "DataType": "VARCHAR2(30)",
                    "Noneable": "NOT None",
                    "Comment": "Target type (as used in target dictionary)"
                },
                {
                    "Keys": None,
                    "ColumnName": "TARGET_DESC",
                    "DataType": "VARCHAR2(250)",
                    "Noneable": None,
                    "Comment": "Description of target type"
                },
                {
                    "Keys": None,
                    "ColumnName": "PARENT_TYPE",
                    "DataType": "VARCHAR2(25)",
                    "Noneable": None,
                    "Comment": "Higher level classification of target_type, allowing grouping of e.g., all 'PROTEIN' targets, all 'NON-MOLECULAR' targets etc."
                }
            ]
        },
        {
            "TableName": "TISSUE_DICTIONARY",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "TISSUE_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key, numeric ID for each tissue."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "UBERON_ID",
                    "DataType": "VARCHAR2(15)",
                    "Noneable": None,
                    "Comment": "Uberon ontology identifier for this tissue."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "PREF_NAME",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": "NOT None",
                    "Comment": "Name for the tissue (in most cases Uberon name)."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "EFO_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "Experimental Factor Ontology identifier for the tissue."
                },
                {
                    "Keys": "FK,UK",
                    "ColumnName": "CHEMBL_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": "NOT None",
                    "Comment": "ChEMBL identifier for this tissue (for use on web interface etc)"
                },
                {
                    "Keys": None,
                    "ColumnName": "BTO_ID",
                    "DataType": "VARCHAR2(20)",
                    "Noneable": None,
                    "Comment": "BRENDA Tissue Ontology identifier for the tissue."
                },
                {
                    "Keys": None,
                    "ColumnName": "CALOHA_ID",
                    "DataType": "VARCHAR2(7)",
                    "Noneable": None,
                    "Comment": "Swiss Institute for Bioinformatics CALOHA Ontology identifier for the tissue."
                }
            ]
        },
        {
            "TableName": "USAN_STEMS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "USAN_STEM_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Numeric primary key."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "STEM",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": "NOT None",
                    "Comment": "Stem defined for use in United States Adopted Names."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "SUBGROUP",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "More specific subgroup of the stem defined for use in United States Adopted Names."
                },
                {
                    "Keys": None,
                    "ColumnName": "ANNOTATION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Meaning of the stem (e.g., the class of compound it applies to)."
                },
                {
                    "Keys": None,
                    "ColumnName": "STEM_CLASS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Indicates whether stem is used as a prefix/infix/suffix/combined prefix and suffix"
                },
                {
                    "Keys": None,
                    "ColumnName": "MAJOR_CLASS",
                    "DataType": "VARCHAR2(100)",
                    "Noneable": None,
                    "Comment": "Protein family targeted by compounds of this class (e.g., GPCR/Ion channel/Protease) where known/applicable. TO BE DEPRECATED."
                }
            ]
        },
        {
            "TableName": "VARIANT_SEQUENCES",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "VARIANT_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key, numeric ID for each sequence variant; -1 for unclassified variants."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "MUTATION",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Details of variant(s) used, with residue positions adjusted to match provided sequence."
                },
                {
                    "Keys": "UK",
                    "ColumnName": "ACCESSION",
                    "DataType": "VARCHAR2(25)",
                    "Noneable": None,
                    "Comment": "UniProt accesion for the representative sequence used as the base sequence (without variation)."
                },
                {
                    "Keys": None,
                    "ColumnName": "VERSION",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Version of the UniProt sequence used as the base sequence."
                },
                {
                    "Keys": None,
                    "ColumnName": "ISOFORM",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Details of the UniProt isoform used as the base sequence where relevant."
                },
                {
                    "Keys": None,
                    "ColumnName": "SEQUENCE",
                    "DataType": "CLOB",
                    "Noneable": None,
                    "Comment": "Variant sequence formed by adjusting the UniProt base sequence with the specified mutations/variations."
                },
                {
                    "Keys": None,
                    "ColumnName": "ORGANISM",
                    "DataType": "VARCHAR2(200)",
                    "Noneable": None,
                    "Comment": "Organism from which the sequence was obtained."
                },
                {
                    "Keys": None,
                    "ColumnName": "TAX_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "NCBI Tax ID for the organism from which the sequence was obtained"
                }
            ]
        },
        {
            "TableName": "VERSION",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "NAME",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": "NOT None",
                    "Comment": "Name of release version"
                },
                {
                    "Keys": None,
                    "ColumnName": "CREATION_DATE",
                    "DataType": "DATE",
                    "Noneable": None,
                    "Comment": "Date database created"
                },
                {
                    "Keys": None,
                    "ColumnName": "COMMENTS",
                    "DataType": "VARCHAR2(2000)",
                    "Noneable": None,
                    "Comment": "Description of release version"
                }
            ]
        },
        {
            "TableName": "WARNING_REFS",
            "Columns": [
                {
                    "Keys": "PK",
                    "ColumnName": "WARNREF_ID",
                    "DataType": "NUMBER",
                    "Noneable": "NOT None",
                    "Comment": "Primary key for the warning reference"
                },
                {
                    "Keys": "FK",
                    "ColumnName": "WARNING_ID",
                    "DataType": "NUMBER",
                    "Noneable": None,
                    "Comment": "Foreign key to the drug_warning table"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_TYPE",
                    "DataType": "VARCHAR2(50)",
                    "Noneable": None,
                    "Comment": "Type/source of reference"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_ID",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Identifier for the reference in the source"
                },
                {
                    "Keys": None,
                    "ColumnName": "REF_URL",
                    "DataType": "VARCHAR2(4000)",
                    "Noneable": None,
                    "Comment": "Full URL linking to the reference"
                }
            ]
        }
    ]
    columns = ",".join([
        "ABSTRACT", "ACCESSION", "ACTION_TYPE", "ACTIVE_INGREDIENT", "ACTIVE_MOLREGNO",
        "ACTIVITY_COMMENT", "ACTIVITY_ID", "ACTSM_ID", "AD_TYPE", "AIDX", "ALERT_ID",
        "ALERT_NAME", "ALERT_SET_ID", "ALOGP", "ANNOTATION", "APPLICANT_FULL_NAME",
        "APPROVAL_DATE", "AP_ID", "AROMATIC_RINGS", "ASPECT", "ASSAY_CATEGORY",
        "ASSAY_CELL_TYPE", "ASSAY_CLASS_ID", "ASSAY_DESC", "ASSAY_ID", "ASSAY_ORGANISM",
        "ASSAY_PARAM_ID", "ASSAY_STRAIN", "ASSAY_SUBCELLULAR_FRACTION", "ASSAY_TAX_ID",
        "ASSAY_TEST_TYPE", "ASSAY_TISSUE", "ASSAY_TYPE", "ASS_CLS_MAP_ID", "AS_ID",
        "ATC_CODE", "AUTHORS", "AVAILABILITY_TYPE", "BAO_ENDPOINT", "BAO_FORMAT",
        "BAO_ID", "BEI", "BINDING_SITE_COMMENT", "BIOCOMP_ID", "BLACK_BOX_WARNING",
        "BTO_ID", "CALOHA_ID", "CANONICAL_SMILES", "CELLOSAURUS_ID", "CELL_DESCRIPTION",
        "CELL_ID", "CELL_NAME", "CELL_ONTOLOGY_ID", "CELL_SOURCE_ORGANISM",
        "CELL_SOURCE_TAX_ID", "CELL_SOURCE_TISSUE", "CHEBI_PAR_ID", "CHEMBL_ID",
        "CHEMBL_RELEASE", "CHEMBL_RELEASE_ID", "CHEMICAL_PROBE", "CHIRALITY", "CIDX",
        "CLASS_LEVEL", "CLASS_TYPE", "CLO_ID", "CL_LINCS_ID", "COMMENTS", "COMPANY",
        "COMPD_ID", "COMPONENT_ID", "COMPONENT_SYNONYM", "COMPONENT_TYPE",
        "COMPOUND_KEY", "COMPOUND_NAME", "COMPSYN_ID", "COMP_CLASS_ID", "COMP_GO_ID",
        "CONFIDENCE", "CONFIDENCE_SCORE", "CONTACT", "COUNTRY", "CO_STEM_ID",
        "CPD_STR_ALERT_ID", "CREATION_DATE", "CURATED_BY", "CX_LOGD", "CX_LOGP",
        "CX_MOST_APKA", "CX_MOST_BPKA", "DATA_VALIDITY_COMMENT", "DB_SOURCE",
        "DB_VERSION", "DDD_ADMR", "DDD_COMMENT", "DDD_ID", "DDD_UNITS", "DDD_VALUE",
        "DEFINITION", "DELIST_FLAG", "DESCRIPTION", "DIRECT_INTERACTION",
        "DISEASE_EFFICACY", "DOC_ID", "DOC_TYPE", "DOI", "DOMAIN_DESCRIPTION",
        "DOMAIN_ID", "DOMAIN_NAME", "DOMAIN_TYPE", "DOSAGE_FORM", "DOSED_INGREDIENT",
        "DRUGIND_ID", "DRUG_PRODUCT_FLAG", "DRUG_RECORD_ID", "DRUG_SUBSTANCE_FLAG",
        "EFO_ID", "EFO_ID_FOR_WARNING_CLASS", "EFO_TERM", "END_POSITION", "ENTITY_ID",
        "ENTITY_TYPE", "ENZYME_NAME", "ENZYME_TID", "FIRST_APPROVAL", "FIRST_IN_CLASS",
        "FIRST_PAGE", "FORMULATION_ID", "FRAC_CLASS_ID", "FRAC_CODE", "FULL_MOLFORMULA",
        "FULL_MWT", "GO_ID", "HBA", "HBA_LIPINSKI", "HBD", "HBD_LIPINSKI", "HEAVY_ATOMS",
        "HELM_NOTATION", "HOMOLOGUE", "HRAC_CLASS_ID", "HRAC_CODE", "INDICATION_CLASS",
        "INDREF_ID", "INGREDIENT", "INNOVATOR_COMPANY", "INORGANIC_FLAG", "IRAC_CLASS_ID",
        "IRAC_CODE", "ISOFORM", "ISSUE", "JOURNAL", "L1", "L2", "L3", "LABEL", "LAST_ACTIVE",
        "LAST_PAGE", "LE", "LEVEL1", "LEVEL1_DESCRIPTION", "LEVEL2", "LEVEL2_DESCRIPTION",
        "LEVEL3", "LEVEL3_DESCRIPTION", "LEVEL4", "LEVEL4_DESCRIPTION", "LEVEL5", "LLE",
        "MAJOR_CLASS", "MAX_PHASE", "MAX_PHASE_FOR_IND", "MECHANISM_COMMENT",
        "MECHANISM_OF_ACTION", "MECREF_ID", "MEC_ID", "MESH_HEADING", "MESH_ID",
        "METABOLITE_RECORD_ID", "METREF_ID", "MET_COMMENT", "MET_CONVERSION", "MET_ID",
        "MOLECULAR_MECHANISM", "MOLECULAR_SPECIES", "MOLECULE_TYPE", "MOLFILE", "MOLREGNO",
        "MOLSYN_ID", "MOL_ATC_ID", "MOL_FRAC_ID", "MOL_HRAC_ID", "MOL_IRAC_ID", "MUTATION",
        "MW_FREEBASE", "MW_MONOISOTOPIC", "NAME", "NATURAL_PRODUCT", "NDA_TYPE",
        "NORMAL_RANGE_MAX", "NORMAL_RANGE_MIN", "NP_LIKENESS_SCORE",
        "NUM_LIPINSKI_RO5_VIOLATIONS", "NUM_RO5_VIOLATIONS", "OC_ID", "ORAL", "ORGANISM",
        "ORPHAN", "PARENTERAL", "PARENT_GO_ID", "PARENT_ID", "PARENT_MOLREGNO",
        "PARENT_TYPE", "PATENT_EXPIRE_DATE", "PATENT_ID", "PATENT_NO", "PATENT_USE_CODE",
        "PATH", "PATHWAY_ID", "PATHWAY_KEY", "PCHEMBL_VALUE", "POLYMER_FLAG",
        "POTENTIAL_DUPLICATE", "PREDBIND_ID", "PREDICTION_METHOD", "PREF_NAME",
        "PREVIOUS_COMPANY", "PRIORITY", "PRODRUG", "PRODUCT_ID", "PROD_PAT_ID",
        "PROTCLASSSYN_ID", "PROTEIN_CLASS_DESC", "PROTEIN_CLASS_ID", "PROTEIN_CLASS_SYNONYM",
        "PSA", "PUBMED_ID", "QED_WEIGHTED", "QUDT_UNITS", "RECORD_ID", "REF_ID", "REF_TYPE",
        "REF_URL", "RELATED_TID", "RELATION", "RELATIONSHIP", "RELATIONSHIP_DESC",
        "RELATIONSHIP_TYPE", "RESEARCH_STEM", "RESULT_FLAG", "RES_STEM_ID", "RGID", "RIDX",
        "RO3_PASS", "ROUTE", "RTB", "SEI", "SELECTIVITY_COMMENT", "SEQUENCE",
        "SEQUENCE_MD5SUM", "SET_NAME", "SHORT_NAME", "SITECOMP_ID", "SITE_ID", "SITE_NAME",
        "SITE_RESIDUES", "SMARTS", "SMID", "SOURCE", "SOURCE_DOMAIN_ID", "SPECIES_GROUP_FLAG",
        "SRC_ASSAY_ID", "SRC_COMPOUND_ID", "SRC_DESCRIPTION", "SRC_ID", "SRC_SHORT_NAME",
        "STANDARD_FLAG", "STANDARD_INCHI", "STANDARD_INCHI_KEY", "STANDARD_RELATION",
        "STANDARD_TEXT_VALUE", "STANDARD_TYPE", "STANDARD_UNITS", "STANDARD_UPPER_VALUE",
        "STANDARD_VALUE", "START_POSITION", "STATUS", "STD_ACT_ID", "STEM", "STEM_CLASS",
        "STRENGTH", "STRUCTURE_TYPE", "SUBGROUP", "SUBMISSION_DATE", "SUBSTRATE_RECORD_ID",
        "SYNONYMS", "SYN_TYPE", "TARGCOMP_ID", "TARGET_DESC", "TARGET_MAPPING", "TARGET_TYPE",
        "TARGREL_ID", "TAX_ID", "TEXT_VALUE", "THERAPEUTIC_FLAG", "TID", "TISSUE_ID",
        "TITLE", "TOID", "TOPICAL", "TRADE_NAME", "TYPE", "UBERON_ID", "UNITS", "UO_UNITS",
        "UPPER_VALUE", "USAN_STEM", "USAN_STEM_DEFINITION", "USAN_STEM_ID", "USAN_SUBSTEM",
        "USAN_YEAR", "VALUE", "VARIANT_ID", "VERSION", "VOLUME", "WARNING_CLASS",
        "WARNING_COUNTRY", "WARNING_DESCRIPTION", "WARNING_ID", "WARNING_TYPE",
        "WARNING_YEAR", "WARNREF_ID", "WHO_NAME", "WITHDRAWN_FLAG", "YEAR"
    ])
    openai_prompt = f"""Given a list of 
    available columns {columns}. Select from the list of available columns the columns that are mentioned in the 
    query.{question}. Return the result as a string with each column name seperated by ,.The column names have to match exactly on every character. "
                   "Uppercase or lowercase differences are okay. Dont add any other text or 
    information."""
    messages = [
        ("system", "You are an agent who is given a query and a list of columns and you are trying to figure out "
                   "which of the columns are mentioned."),
        ("human", openai_prompt),
    ]
    response = llm.invoke(messages).content
    columns = response.split(",")
    openai_prompt = f"""Give description of available columns in the tables in a database as a list of json objects 
    {json_objects} Where 
    each object represents one database table. Build a SQL query that connects the columns
     {columns[0]} and {columns[1]}. Return the query as a string. Add bigquery-public-data.ebi_chembl before the 
     table names. Limit to the first 10 rows. Table names should be in lower case.Only return the query nothing else. """
    messages = [
        ("system", "You are an agent who is given information about the tables in a sql database in the form of a "
                   "json, and you are trying to construct a sql query to relate two columns"),
        ("human", openai_prompt),
    ]
    query = str(llm.invoke(messages).content.replace("sql", "").replace("```", ""))
    query_job = client.query(query)
    rows = query_job.result()
    row_string = rows.to_dataframe().to_string()
    return {"success": True, "data": row_string}


@web_app.post("/answer")
async def endpoint(json_data:Dict,token: HTTPAuthorizationCredentials = Depends(auth_scheme),
                   ):
    query = "What is the correlation between ALogP and black box warning?"
    if token.credentials != os.environ["AUTH_TOKEN"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    query = json_data["message"]
    blob = await answer.remote.aio(query)
    return json.dumps({"data": blob})


@web_app.get("/")
async def root():
    return {"message": "Hi there! I am DrugCrow!"}


@stub.function(secrets=[Secret.from_name("agihack-token")])
@asgi_app()
def app():
    return web_app
