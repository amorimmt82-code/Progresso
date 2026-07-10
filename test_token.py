"""Test the captured Bearer token against the gRPC server."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJEZXNrdG9wQ2xpZW50IC0gTlVDVEVDTklDT1MgKG1hdGhldXMuYW1vcmltKSAoVXNlcjogTWFyaWFuYSkiLCJqdGkiOiI1YTc5MDMxMi03NTg2LTRlNDktYmY3Mi1hMTc2NTY5YjA0MzQiLCJpYXQiOjE3NzQyNjM2NDksIngtdHlwZSI6ImFwcGxpY2F0aW9uX2luc3RhbmNlX3VzZXIiLCJ4LWFwcGxpY2F0aW9uLWluc3RhbmNlLWlkIjoiMDE5Y2Y2YjE2ZjliMWNlZmNiYTU1YmRhMWFiZjI0NWIiLCJ4LWFwcGxpY2F0aW9uLWluc3RhbmNlLW5hbWUiOiJEZXNrdG9wQ2xpZW50IC0gTlVDVEVDTklDT1MgKG1hdGhldXMuYW1vcmltKSIsIngtYXBwbGljYXRpb24taW5zdGFsbGF0aW9uLWlkIjoiMDE5Y2Y2YjE2Zjk4NDEzNDNkNTlmZDA0ZjczZDllMmMiLCJ4LWFwcGxpY2F0aW9uLWluc3RhbGxhdGlvbi1uYW1lIjoiRGVza3RvcENsaWVudCAtIE5VQ1RFQ05JQ09TIiwieC1hcHBsaWNhdGlvbi1pZCI6IjAxOWJkYWRkMjg2ZjgzNjIyYjBhMGQxODAwOWEwMTQ1IiwieC1hcHBsaWNhdGlvbi1uYW1lIjoiRGVza3RvcENsaWVudCIsIngtYXBwbGljYXRpb24tdHlwZSI6IkRlc2t0b3BDbGllbnQiLCJ4LWNvbXB1dGVyLW5hbWUiOiJOVUNURUNOSUNPUyIsIngtdXNlci1pZCI6IjAxOWM5ZmNjZWRlZDczZWQyN2ZjMDcxZmQzOWNlNzgwIiwieC11c2VyLW5hbWUiOiJNYXJpYW5hIiwieC11c2VyLXR5cGUiOiJDdXN0b21lckFkbWluIiwieC1wcml2aWxlZ2VzIjoiUmVhZFJvbGVzLFJlYWRSZmlkVGFncyxXcml0ZVJmaWRUYWdzLFJlYWRVc2VycyxXcml0ZVVzZXJzLFJlYWRQcml2aWxlZ2VzLE1hbmFnZVVzZXJBY2Nlc3NDb250cm9sLFdyaXRlRG93bnRpbWVSZWFzb25zLFJlYWRBY3Rpdml0aWVzLFdyaXRlQWN0aXZpdGllcyxSZWFkRGFzaGJvYXJkcyxXcml0ZURhc2hib2FyZHMsUmVhZEdvb2RzUmVjZWlwdHMsV3JpdGVHb29kc1JlY2VpcHRzLFJlYWRTdG9yYWdlQXJlYXMsV3JpdGVTdG9yYWdlQXJlYXMsUmVhZFByb2Nlc3NlcyxXcml0ZVByb2Nlc3NlcyxSZWFkUHJvY2Vzc0NvbmZpZ3VyYXRpb25zLFJlYWRCdXNpbmVzc1BhcnRuZXJzLFdyaXRlQnVzaW5lc3NQYXJ0bmVycyxSZWFkRGV2aWNlcyxSZWFkTGluZXMsV3JpdGVMaW5lcyxSZWFkTG9naW5zLFJlYWRBcnRpY2xlcyxXcml0ZUFydGljbGVzLFJlYWRPcmRlcnMsV3JpdGVMb2dpbnMsUmVhZFJlcG9ydHMsV3JpdGVSZXBvcnRzLFdyaXRlT3JkZXJzLFN0YXJ0U3RvcE9yZGVycyxSZWFkQ3VsdGl2YXRpb25BcmVhcyxXcml0ZUN1bHRpdmF0aW9uQXJlYXMsUmVhZExhYmVscyxXcml0ZU9yZGVyVGVtcGxhdGVzLFJlYWREZXZpY2VBcnRpY2xlcyxXcml0ZURldmljZUFydGljbGVzLFdyaXRlTGFiZWxzLFJlYWRSYXdNYXRlcmlhbHMsUmVhZFRyYWNlYWJpbGl0eURhdGEsUmVhZFBhY2thZ2luZ01hdGVyaWFscyxXcml0ZVBhY2thZ2luZ01hdGVyaWFscyxSZWFkT3JkZXJUZW1wbGF0ZXMsV3JpdGVQcm9jZXNzQ29uZmlndXJhdGlvbnMsV3JpdGVSYXdNYXRlcmlhbHMsUmVhZERvd250aW1lUmVhc29ucyIsIm5iZiI6MTc3NDI2MzY0NCwiZXhwIjoxNzc0MzUwMDQ5LCJpc3MiOiJnYW1tYSIsImF1ZCI6ImdhbW1hIn0.XutwgqcA04VYNgD8EsfkE-wccos__a1UjcuXeVqmmVEJSEoHNRjkpvVsEDICiFTfzo3AYc6n6D0i_UQ73BFDRV0d2SIvL7_HiLaBFuvy8k0f5oRYRF6I1EmOHQ-FB6vN10zGUHH-FtDNFDf7jqKFGCYlSJ7V_qL-wMR9CzJss5PvzfAxmrgElnmNXag9u8-NoroODPSENFNfzNZF7ucg6lAaKmTsgT9DXIg0xLfgR0IJd9zJNrqycTWzRy3F2NLmcnLCJmgQH3Se0uzSl58sPPsHNpIGP3qchHmDH8UpQ-bWqxDdQUtXJB0BUcGX1qINBhVKka618QvdNMmMif35zRGVLLyz94gP49B9x8s-dvNyLxjSblZT-Hq61xWc5LsTKq-hHbqtSjrqebaC4Yx0cVxE22aDYxF_CayT4n1_UrW4DQDcOuVuNVVZU0CDYsaGL10_Limd2qFCjwDbmUzmA4cf6UgpQDVzZxizF0Bv_vynoNuN7IKZPyvhjd4lc6xmw4CHSyIErMGazwUcwThISrKUGdumIyb4yJP-UWjGOlXkabSOQ0L0acG5RR_dc55mj2yUW8MWo2Rf8Lgo99bbYoHp_wcw3zz9dpJ8VPfyByd1e0BRQ66RIXdL1zQx91YqOM6OX9QPSNAZK0m6UG6VCPGZKyoB-oFs5ZjV-Yzu-ug"

pool = DescriptorPool()
channel = grpc.insecure_channel("192.168.30.8:37270")
stub = reflection_pb2_grpc.ServerReflectionStub(channel)
added_files = set()


def add_file(filename):
    if filename in added_files:
        return
    req = reflection_pb2.ServerReflectionRequest(file_by_filename=filename)
    for resp in stub.ServerReflectionInfo(iter([req])):
        if resp.HasField("file_descriptor_response"):
            for b in resp.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added_files:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added_files.add(fd.name)


def add_sym(symbol):
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    for resp in stub.ServerReflectionInfo(iter([req])):
        if resp.HasField("file_descriptor_response"):
            for b in resp.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added_files:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added_files.add(fd.name)


symbols = [
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest",
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse",
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataAdHocRequest",
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataResponse",
    "topcontrol.gamma.ps.Decimal",
    "google.protobuf.Duration",
]
for s in symbols:
    add_sym(s)

print(f"Pool: {len(added_files)} files loaded")

meta = [("authorization", f"Bearer {TOKEN}")]

# === Weighing Report ===
WReq = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest"))
WResp = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse"))

req = WReq()
req.time_filter = 3   # TODAY
req.time_dimension = 1  # NONE
req.dimensions.extend([3, 4, 1])  # USER, DEVICE, ARTICLE
req.metrics.extend([14, 1])  # WEIGHT_KG, QUANTITY

print("\n=== WEIGHING REPORT (TODAY) ===")
try:
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetWeighingReportDataAdHoc",
        request_serializer=WReq.SerializeToString,
        response_deserializer=WResp.FromString,
    )(req, metadata=meta)
    print(f"Items: {len(resp.items)}")
    for it in resp.items[:10]:
        wkg = it.weight_kg.value if it.HasField("weight_kg") else "?"
        qty = it.quantity.value if it.HasField("quantity") else "?"
        print(f"  {it.user_display_name} | {it.device_name} | {it.article_name} | {wkg}kg | qty={qty}")
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# === Login Report ===
LReq = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataAdHocRequest"))
LResp = GetMessageClass(pool.FindMessageTypeByName(
    "topcontrol.gamma.ps.core.analytics.GetLoginReportDataResponse"))

req2 = LReq()
req2.time_filter = 3
req2.time_dimension = 1
req2.dimensions.extend([1, 3, 4])  # USER, DEVICE, ACTIVITY
req2.metrics.extend([1])  # WORKING_TIME

print("\n=== LOGIN REPORT (TODAY) ===")
try:
    resp2 = channel.unary_unary(
        "/topcontrol.gamma.ps.core.analytics.ReportService/GetLoginReportDataAdHoc",
        request_serializer=LReq.SerializeToString,
        response_deserializer=LResp.FromString,
    )(req2, metadata=meta)
    print(f"Items: {len(resp2.items)}")
    for it in resp2.items[:10]:
        wt = ""
        if it.HasField("working_time"):
            s = it.working_time.seconds
            wt = f"{s // 3600}h{(s % 3600) // 60}m{s % 60}s"
        print(f"  {it.user_name} | {it.device_name} | {wt}")
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

channel.close()
print("\nDone!")
