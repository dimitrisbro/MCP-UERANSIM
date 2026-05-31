from typing import List, Optional
from pydantic import BaseModel, Field


# ── gNB models ────────────────────────────────────────────────────────────────

class GnbConfiguration(BaseModel):
    link_ip: str = Field(description="Link interface IP address")
    ngap_ip: str = Field(description="NGAP interface IP address")
    gtp_ip: str = Field(description="GTP interface IP address")
    amf_address: str = Field(description="AMF IP address")
    amf_port: str = Field(description="AMF port")
    mcc: str = Field(default="999", description="Mobile Country Code")
    mnc: str = Field(default="70", description="Mobile Network Code")
    tac: int = Field(default=1, description="Tracking Area Code")
    nci: str = Field(default="0x000000010", description="NR Cell Identity (36-bit hex)")
    id_length: int = Field(default=32, description="NR gNB ID length in bits [22..32]")
    slice_sst: int = Field(default=1, description="Primary slice SST")
    slice_sd: Optional[int] = Field(default=None, description="Primary slice SD (optional)")
    cell_access_type: str = Field(default="nr", description="Cell access type (nr, nr-leo, nr-meo, nr-geo, nr-othersat)")
    gtp_advertise_ip: Optional[str] = Field(default=None, description="GTP advertise IP for NAT scenarios")
    ignore_stream_ids: bool = Field(default=True, description="Ignore SCTP stream ID errors")


class GnbContainer(BaseModel):
    id: str = Field(description="Container ID")
    name: str = Field(description="Container name")
    status: str = Field(description="Container status")
    created: str = Field(description="Creation timestamp")


class GnbCreateResponse(BaseModel):
    status: str = Field(description="Operation status")
    container_id: str = Field(description="Created container ID")
    container_name: str = Field(description="Container name")
    configuration: GnbConfiguration = Field(description="Container configuration")
    message: Optional[str] = Field(description="Additional message", default=None)


class GnbListResponse(BaseModel):
    status: str = Field(description="Operation status")
    containers: List[GnbContainer] = Field(description="List of gNB containers")
    count: int = Field(description="Number of containers")
    message: Optional[str] = Field(description="Additional message", default=None)


class GnbOperationResponse(BaseModel):
    status: str = Field(description="Operation status (success/error)")
    message: str = Field(description="Operation message")
    container: Optional[str] = Field(description="Container ID or name", default=None)
    logs: Optional[str] = Field(description="Container logs", default=None)


# ── UE models ─────────────────────────────────────────────────────────────────

class UeConfiguration(BaseModel):
    gnb_search_list: str = Field(description="gNB search list IP addresses")
    supi: Optional[str] = Field(default=None, description="SUPI (imsi-MCCMNCMSISDN)")
    mcc: str = Field(default="999", description="Mobile Country Code")
    mnc: str = Field(default="70", description="Mobile Network Code")
    key: Optional[str] = Field(default=None, description="Subscription key (32 hex chars)")
    op: Optional[str] = Field(default=None, description="Operator code (32 hex chars)")
    op_type: str = Field(default="OPC", description="Operator code type: OP or OPC")
    slice_sst: int = Field(default=1, description="Primary slice SST")
    slice_sd: Optional[int] = Field(default=None, description="Primary slice SD (optional)")
    session_apn: str = Field(default="internet", description="PDU session APN")
    session_type: str = Field(default="IPv4", description="PDU session type")
    tun_netmask: str = Field(default="255.255.255.0", description="TUN interface netmask")


class UeContainer(BaseModel):
    id: str = Field(description="Container ID")
    name: str = Field(description="Container name")
    status: str = Field(description="Container status")
    created: str = Field(description="Creation timestamp")


class UeCreateResponse(BaseModel):
    status: str = Field(description="Operation status")
    container_id: str = Field(description="Created container ID")
    container_name: str = Field(description="Container name")
    configuration: UeConfiguration = Field(description="Container configuration")
    message: Optional[str] = Field(description="Additional message", default=None)


class UeListResponse(BaseModel):
    status: str = Field(description="Operation status")
    containers: List[UeContainer] = Field(description="List of UE containers")
    count: int = Field(description="Number of containers")
    message: Optional[str] = Field(description="Additional message", default=None)


class UeOperationResponse(BaseModel):
    status: str = Field(description="Operation status (success/error)")
    message: str = Field(description="Operation message")
    container: Optional[str] = Field(description="Container ID or name", default=None)
    logs: Optional[str] = Field(description="Container logs", default=None)
