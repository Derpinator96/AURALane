"""Local providers: everything runs on localhost with no AWS account."""
from core.providers.local.blob import FileBlob
from core.providers.local.devauth import DevAuth
from core.providers.local.dynamo import DynamoLocalTable
from core.providers.local.inference import InProcessInference
from core.providers.local.llm import TemplateLLM
from core.providers.local.orthanc import OrthancDatastore

__all__ = ["FileBlob", "DevAuth", "DynamoLocalTable", "InProcessInference",
           "TemplateLLM", "OrthancDatastore"]
