from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.domain.mcp_servers.repository import McpServerRepository
from app.domain.mcp_servers.service import McpServerService
from shared.errors import ValidationFailedError

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class McpEntryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    secret: bool
    is_set: bool
    value: str | None = None

    @model_validator(mode="before")
    @classmethod
    def remove_secret_value(cls, value):
        if isinstance(value, dict) and value.get("secret") is True:
            return {key: item for key, item in value.items() if key not in {"value", "ciphertext"}}
        return value

    @model_serializer(mode="wrap")
    def serialize_secret_safely(self, handler):
        data = handler(self)
        if self.secret:
            data.pop("value", None)
        return data


class StdioTransportResponse(BaseModel):
    type: Literal["stdio"]
    command: str
    args: list[str]
    env: list[McpEntryResponse]


class HttpTransportResponse(BaseModel):
    type: Literal["http"]
    url: str
    headers: list[McpEntryResponse]


McpTransportResponse = Annotated[StdioTransportResponse | HttpTransportResponse, Field(discriminator="type")]


class McpServerListResponse(BaseModel):
    id: str
    name: str
    owner_user_id: str
    visibility: str
    group_id: str | None


class McpServerResponse(McpServerListResponse):
    transport: McpTransportResponse
    updated_at: str | None


def get_mcp_server_service(db: AsyncSession = Depends(get_db)) -> McpServerService:
    return McpServerService(McpServerRepository(db))


class EntryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=256)
    secret: bool
    action: Literal["replace", "keep", "remove"]
    value: str | None = None


class StdioTransport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["stdio"]
    command: str = Field(min_length=1, max_length=2048)
    args: list[str] = Field(max_length=256)
    env: list[EntryWrite] = Field(default_factory=list, max_length=256)


class HttpTransport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["http"]
    url: str = Field(min_length=1, max_length=4096)
    headers: list[EntryWrite] = Field(default_factory=list, max_length=256)


Transport = Annotated[StdioTransport | HttpTransport, Field(discriminator="type")]


class McpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    visibility: Literal["personal", "group", "global"] = "personal"
    group_id: str | None = Field(default=None, max_length=36)
    transport: Transport


class McpPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    visibility: Literal["personal", "group", "global"] | None = None
    group_id: str | None = Field(default=None, max_length=36)
    transport: Transport | None = None


def _body_values(body):
    values = body.model_dump(exclude_unset=True)
    for field in ("name", "visibility", "transport"):
        if field in values and values[field] is None:
            raise ValidationFailedError("errors.mcp_server.field_required")
    if "transport" in values:
        values["transport"] = body.transport.model_dump(exclude_none=True)
    return values


@router.get("", response_model=list[McpServerListResponse])
async def list_mcp_servers(user=Depends(get_current_user), service: McpServerService = Depends(get_mcp_server_service)):
    return await service.list_visible(user.id)


@router.get("/{server_id}", response_model=McpServerResponse)
async def get_mcp_server(server_id: str, user=Depends(get_current_user), service: McpServerService = Depends(get_mcp_server_service)):
    return await service.get_visible(user.id, server_id)


@router.post("", status_code=201, response_model=McpServerResponse)
async def create_mcp_server(body: McpCreate, user=Depends(get_current_user), service: McpServerService = Depends(get_mcp_server_service)):
    return await service.create(user, body.model_dump(exclude_none=True))


@router.patch("/{server_id}", response_model=McpServerResponse)
async def update_mcp_server(server_id: str, body: McpPatch, user=Depends(get_current_user), service: McpServerService = Depends(get_mcp_server_service)):
    return await service.update(user, server_id, _body_values(body))


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(server_id: str, user=Depends(get_current_user), service: McpServerService = Depends(get_mcp_server_service)):
    await service.delete(user, server_id)
