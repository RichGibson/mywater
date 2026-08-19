import pytest
from unittest.mock import MagicMock, patch

from photos import MAX_PHOTO_SIZE_BYTES, PhotoValidationError, validate_photo


def test_validate_photo_accepts_small_jpeg():
    validate_photo(b"x" * 100, "image/jpeg")


def test_validate_photo_rejects_disallowed_content_type():
    with pytest.raises(PhotoValidationError):
        validate_photo(b"x" * 100, "image/gif")


def test_validate_photo_rejects_oversized_content():
    with pytest.raises(PhotoValidationError):
        validate_photo(b"x" * (MAX_PHOTO_SIZE_BYTES + 1), "image/jpeg")


def test_validate_photo_accepts_content_at_exact_size_limit():
    validate_photo(b"x" * MAX_PHOTO_SIZE_BYTES, "image/png")


def test_upload_photo_validates_before_uploading():
    from photos import upload_photo

    with pytest.raises(PhotoValidationError):
        upload_photo(b"x" * 100, "image/gif")


@patch.dict(
    "os.environ",
    {
        "R2_ACCOUNT_ID": "test-account",
        "R2_ACCESS_KEY_ID": "test-key",
        "R2_SECRET_ACCESS_KEY": "test-secret",
        "R2_BUCKET_NAME": "test-bucket",
        "R2_PUBLIC_BASE_URL": "https://photos.example.com",
    },
)
def test_upload_photo_puts_object_and_returns_public_url():
    from photos import upload_photo

    mock_client = MagicMock()
    with patch("photos.boto3.client", return_value=mock_client) as mock_boto_client:
        url = upload_photo(b"fake-jpeg-bytes", "image/jpeg")

    mock_boto_client.assert_called_once()
    call_kwargs = mock_boto_client.call_args.kwargs
    assert call_kwargs["endpoint_url"] == "https://test-account.r2.cloudflarestorage.com"

    mock_client.put_object.assert_called_once()
    put_kwargs = mock_client.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == "test-bucket"
    assert put_kwargs["Body"] == b"fake-jpeg-bytes"
    assert put_kwargs["ContentType"] == "image/jpeg"
    assert put_kwargs["Key"].endswith(".jpg")

    assert url == f"https://photos.example.com/{put_kwargs['Key']}"
