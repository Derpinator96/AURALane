"""AWS providers. STUBS until Prompt 3: every method raises NotImplementedError
naming the service it will call.

_dynamodb.py is the exception: it is the one DynamoDB implementation, already
used by the local provider against DynamoDB Local. DynamoTable below stays a
stub until it is run against real DynamoDB.
"""
from core.ports import (AuthPort, BlobPort, DatastorePort, InferencePort, LLMPort,
                        TablePort)


def _todo(service):
    def method(self, *a, **k):
        raise NotImplementedError(f"{service}: not wired yet (Prompt 3)")
    return method


class HealthImagingDatastore(DatastorePort):
    import_study = _todo("AWS HealthImaging StartDICOMImportJob")
    search = _todo("AWS HealthImaging SearchImageSets")
    get_metadata = _todo("AWS HealthImaging GetImageSetMetadata")
    get_frame = _todo("AWS HealthImaging GetImageFrame")
    frame_url = _todo("AWS HealthImaging DICOMweb frame URL")


class S3Blob(BlobPort):
    put = _todo("Amazon S3 PutObject")
    get = _todo("Amazon S3 GetObject")
    delete = _todo("Amazon S3 DeleteObject")
    presigned_url = _todo("Amazon S3 presigned GetObject URL")


class DynamoTable(TablePort):
    put_item = _todo("Amazon DynamoDB PutItem")
    get_item = _todo("Amazon DynamoDB GetItem")
    query = _todo("Amazon DynamoDB Query")
    scan = _todo("Amazon DynamoDB Scan")
    append_audit = _todo("Amazon DynamoDB PutItem (audit, conditional)")


class CognitoAuth(AuthPort):
    verify = _todo("Amazon Cognito JWT verification")


class LambdaSageMakerInference(InferencePort):
    score = _todo("AWS Lambda Invoke / Amazon SageMaker InvokeEndpointAsync")


class BedrockLLM(LLMPort):
    draft = _todo("Amazon Bedrock InvokeModel (blocked at account level)")
