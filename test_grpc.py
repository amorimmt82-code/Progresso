"""Teste de conexão gRPC direta com o servidor TopControl."""
import grpc
import uuid
import platform
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

pool = DescriptorPool()
channel = grpc.insecure_channel("192.168.30.8:37270")
stub = reflection_pb2_grpc.ServerReflectionStub(channel)

added_files = set()


def add_file_to_pool(filename):
    if filename in added_files:
        return
    req = reflection_pb2.ServerReflectionRequest(file_by_filename=filename)
    responses = stub.ServerReflectionInfo(iter([req]))
    for resp in responses:
        if resp.HasField("file_descriptor_response"):
            for fd_bytes in resp.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(fd_bytes)
                if fd.name not in added_files:
                    for dep in fd.dependency:
                        add_file_to_pool(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added_files.add(fd.name)


def add_symbol_to_pool(symbol):
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    responses = stub.ServerReflectionInfo(iter([req]))
    for resp in responses:
        if resp.HasField("file_descriptor_response"):
            for fd_bytes in resp.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(fd_bytes)
                if fd.name not in added_files:
                    for dep in fd.dependency:
                        add_file_to_pool(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added_files.add(fd.name)


# Register all needed types
for sym in [
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.accesscontrol.AccessControlService",
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest",
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataAdHocRequest",
    "topcontrol.gamma.ps.core.accesscontrol.LoginApplicationRequest",
    "topcontrol.gamma.ps.core.accesscontrol.LoginResponse",
    "topcontrol.gamma.ps.core.accesscontrol.LoginSessionInfo",
    "topcontrol.gamma.ps.core.accesscontrol.ApplicationInstallationInfo",
    "topcontrol.gamma.ps.core.accesscontrol.ApplicationInstanceInfo",
    "topcontrol.gamma.ps.Decimal",
    "topcontrol.gamma.ps.Uuid",
    "topcontrol.gamma.ps.LocalDateTimeRange",
    "topcontrol.gamma.ps.LocalDate",
    "topcontrol.gamma.ps.LocalDateTime",
    "topcontrol.gamma.ps.MultilingualString",
    "google.protobuf.Duration",
    "google.protobuf.Empty",
]:
    add_symbol_to_pool(sym)

print(f"Pool files: {len(added_files)}")

# ===== STEP 1: Login =====
LoginAppReqDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.accesscontrol.LoginApplicationRequest"
)
LoginAppReq = GetMessageClass(LoginAppReqDesc)

LoginRespDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.accesscontrol.LoginResponse"
)
LoginRespCls = GetMessageClass(LoginRespDesc)

LoginSessionInfoDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.accesscontrol.LoginSessionInfo"
)
LoginSessionInfo = GetMessageClass(LoginSessionInfoDesc)

AppInstInfoDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.accesscontrol.ApplicationInstallationInfo"
)
AppInstInfo = GetMessageClass(AppInstInfoDesc)

AppInstanceInfoDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.accesscontrol.ApplicationInstanceInfo"
)
AppInstanceInfo = GetMessageClass(AppInstanceInfoDesc)

# Build login request with real DesktopClient UIDs from registry
APP_INSTANCE_UID = "9c9394b9c82340c6816c7128ec46a606"  # from HKCU (no dashes)
APP_INSTALL_UID = "9113fc6974a94fb6926dcdcc7dd1a9bf"   # from HKLM (no dashes)

login_req = LoginAppReq()
session_info = login_req.login_session_info
session_info.application_uid = str(uuid.uuid4())

ii = session_info.application_installation_info
ii.uid = APP_INSTALL_UID
ii.name = "DesktopClient"
ii.application_version = "1.0.0"
ii.computer_name = platform.node()

ai = session_info.application_instance_info
ai.uid = APP_INSTANCE_UID
ai.name = "DesktopClient"

print("\nAttempting LoginApplication with real UIDs...")
login_method = "/topcontrol.gamma.ps.core.accesscontrol.AccessControlService/LoginApplication"
access_token = None
try:
    login_resp = channel.unary_unary(
        login_method,
        request_serializer=LoginAppReq.SerializeToString,
        response_deserializer=LoginRespCls.FromString,
    )(login_req)
    access_token = login_resp.access_token
    print(f"Login SUCCESS! Token: {access_token[:80]}...")
    print(f"Is admin: {login_resp.is_administrator}")
except grpc.RpcError as e:
    print(f"LoginApplication failed: {e.code()} - {e.details()}")

if not access_token:
    print("\nLogin failed!")
    channel.close()
    exit(1)

# ===== STEP 2: Use token for authenticated calls =====
# Create new channel with auth metadata
auth_metadata = [("authorization", f"Bearer {access_token}")]

WeighReqDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"
)
WeighReq = GetMessageClass(WeighReqDesc)

WeighRespDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"
)
WeighResp = GetMessageClass(WeighRespDesc)

# Request: today, no time grouping, dimensions=[USER, DEVICE, ARTICLE], metrics=[WEIGHT_KG, QUANTITY]
req = WeighReq()
req.time_filter = 3  # TODAY
req.time_dimension = 1  # NONE
req.dimensions.extend([3, 4, 1])  # USER=3, DEVICE=4, ARTICLE=1
req.metrics.extend([14, 1])  # WEIGHT_KG=14, QUANTITY=1

method = "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc"
print("\nCalling GetWeighingReportDataAdHoc...")
try:
    resp = channel.unary_unary(
        method,
        request_serializer=WeighReq.SerializeToString,
        response_deserializer=WeighResp.FromString,
    )(req, metadata=auth_metadata)

    print(f"\n=== WEIGHING DATA (TODAY) ===")
    print(f"Items: {len(resp.items)}")
    for item in resp.items[:10]:
        wkg = ""
        if item.HasField("weight_kg"):
            wkg = item.weight_kg.value
        qty = ""
        if item.HasField("quantity"):
            qty = item.quantity.value
        print(f"  {item.user_display_name} | {item.device_name} | {item.article_name} | {wkg}kg | qty={qty}")
except grpc.RpcError as e:
    print(f"Weighing call failed: {e.code()} - {e.details()}")

# Now test Login report
LoginReportReqDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataAdHocRequest"
)
LoginReportReq = GetMessageClass(LoginReportReqDesc)

LoginReportRespDesc = pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataResponse"
)
LoginReportResp = GetMessageClass(LoginReportRespDesc)

req2 = LoginReportReq()
req2.time_filter = 3  # TODAY
req2.time_dimension = 1  # NONE
req2.dimensions.extend([1, 3, 4])  # USER=1, DEVICE=3, ACTIVITY=4
req2.metrics.extend([1])  # WORKING_TIME=1

method2 = "/topcontrol.gamma.ps.core.analytics.ReportService/GetLoginReportDataAdHoc"
print("\nCalling GetLoginReportDataAdHoc...")
try:
    resp2 = channel.unary_unary(
        method2,
        request_serializer=LoginReportReq.SerializeToString,
        response_deserializer=LoginReportResp.FromString,
    )(req2, metadata=auth_metadata)

    print(f"\n=== LOGIN DATA (TODAY) ===")
    print(f"Items: {len(resp2.items)}")
    for item in resp2.items[:10]:
        wt = ""
        if item.HasField("working_time"):
            secs = item.working_time.seconds
            wt = f"{secs // 3600}h{(secs % 3600) // 60}m{secs % 60}s"
        print(f"  {item.user_name} | {item.device_name} | {wt}")
except grpc.RpcError as e:
    print(f"Login report call failed: {e.code()} - {e.details()}")

# Logout
try:
    EmptyDesc = pool.FindMessageTypeByName("google.protobuf.Empty")
    EmptyCls = GetMessageClass(EmptyDesc)
    channel.unary_unary(
        "/topcontrol.gamma.ps.core.accesscontrol.AccessControlService/Logout",
        request_serializer=EmptyCls.SerializeToString,
        response_deserializer=EmptyCls.FromString,
    )(EmptyCls(), metadata=auth_metadata)
    print("\nLogout OK")
except Exception:
    pass

channel.close()
print("\nDone!")
