import pyarrow as pa
import os
from time import sleep
from foundry.v2 import FoundryClient
from foundry import UserTokenAuth, ConfidentialClientAuth
from dataclasses import dataclass
from pydantic import Field
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Iterator
from mcp.server.fastmcp import FastMCP, Context
from typing import Iterator


@dataclass
class AppContext:
    foundry_client: FoundryClient
    ontology_id: str

@dataclass
class ObjectType:
    name: str
    description: str
    properties: list[str]
    primary_key: str


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""

    token = os.environ.get("TOKEN")

    if token:
        auth = UserTokenAuth(token=token)
    else:
        auth = ConfidentialClientAuth(
            client_id=os.environ["CLIENT_ID"],
            client_secret=os.environ["CLIENT_SECRET"],
            scopes=os.environ.get("SCOPES")
        )

    foundry_client = FoundryClient(auth=auth, hostname=os.environ["HOSTNAME"])

    yield AppContext(
        foundry_client=foundry_client,
        ontology_id=os.environ["ONTOLOGY_ID"]
    )

mcp = FastMCP("My App", lifespan=app_lifespan, dependencies=["foundry-platform-sdk"])

@mcp.tool()
def list_ontology_types(ctx: Context) -> Iterator[str]:
    """ List all the ontology types """
    foundry_client: FoundryClient = ctx.request_context.lifespan_context.foundry_client
    ontology_id = ctx.request_context.lifespan_context.ontology_id

    return [
        ObjectType(
            name=object_type.api_name,
            description=object_type.description,
            properties=list(object_type.properties.keys()),
            primary_key=object_type.primary_key
        )
    for object_type in foundry_client.ontologies.Ontology.ObjectType.list(ontology_id)]


@mcp.tool()
def query_ontology_type(
    ctx: Context,
    where: dict[any, any] = Field(description="Filter conditions"),
    object_type: str = Field(description="Name of a ontology type (e.g. User, Article, etc.)")
) -> dict:
    """ Query for objects in a given ontology type.
        Use list_ontology_types to get the list of available types
    """

    foundry_client: FoundryClient = ctx.request_context.lifespan_context.foundry_client
    ontology_id: str = ctx.request_context.lifespan_context.ontology_id

    all_properties = [prop for prop in foundry_client.ontologies.OntologyObject.list(
        ontology_id,
        object_type,
        page_size=1
    ).data[0] if not prop.startswith('__') ]

    response = foundry_client.ontologies.OntologyObject.search(
        ontology_id,
        object_type,
        select=all_properties,
        exclude_rid=True,
        where=where
    )

    return response.data


@mcp.tool()
def query_dataset(ctx: Context, query: str) -> dict:
    """ Query a dataset using Spark SQL dialect e.g. "SELECT COUNT(*) FROM `dataset_rid`" """
    foundry_client: FoundryClient = ctx.request_context.lifespan_context.foundry_client
    query_id = foundry_client.sql_queries.Query.execute(
        query=query,
        preview=True
    ).query_id

    succeeded = False

    while not succeeded:
        status = foundry_client.sql_queries.Query.get_status(query_id, preview=True)
        succeeded = status.type == "succeeded"
        if status.type == "failed" or status.type == "cancelled":
            raise Exception("Query failed or cancelled")
        sleep(2)

    results = foundry_client.sql_queries.Query.get_results(query_id, preview=True)

    return pa.ipc.open_stream(results).read_all().to_pandas().to_json()


@mcp.tool()
def list_functions(ctx: Context) -> Iterator[str]:
    """ List all available functions"""

    foundry_client: FoundryClient = ctx.request_context.lifespan_context.foundry_client
    ontology_id: str = ctx.request_context.lifespan_context.ontology_id

    return [ontologyType for ontologyType in foundry_client.ontologies.Ontology.QueryType.list(ontology_id)]


@mcp.tool()
def execute_function(query_api_name: str, parameters: dict, ctx: Context):
    """ Execute a function using given parameters """

    foundry_client: FoundryClient = ctx.request_context.lifespan_context.foundry_client
    ontology_id: str = ctx.request_context.lifespan_context.ontology_id

    results = foundry_client.ontologies.Query.execute(
        ontology_id,
        query_api_name,
        parameters=parameters
    )
    return results


def main():
    mcp.run()

if __name__ == "__main__":
    main()