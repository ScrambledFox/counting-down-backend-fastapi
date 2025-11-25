from typing import Protocol


class S3Client(Protocol):
    def upload_file(self, file_path: str, bucket_name: str, object_name: str) -> None:
        """Uploads a file to the specified S3 bucket."""
        ...

    def download_file(self, bucket_name: str, object_name: str, file_path: str) -> None:
        """Downloads a file from the specified S3 bucket."""
        ...

    def delete_file(self, bucket_name: str, object_name: str) -> None:
        """Deletes a file from the specified S3 bucket."""
        ...
