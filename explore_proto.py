"""Quick script to explore gRPC proto descriptors for time filter enums and date fields."""
import os
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool

GRPC_SERVER = "192.168.30.8:37270"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else None

channel = grpc.insecure_channel(GRPC_SERVER)

# Build pool
pool = DescriptorPool()
stub = reflection_pb2_grpc.ServerReflectionStub(channel)
added = set()
meta = [("authorization", f"Bearer {token}")] if token else None

def add_file(fn):
    if fn in added:
        return
    req = reflection_pb2.ServerReflectionRequest(file_by_filename=fn)
    for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
        if r.HasField("file_descriptor_response"):
            for b in r.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added.add(fd.name)

def add_sym(symbol):
    req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
        if r.HasField("file_descriptor_response"):
            for b in r.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except Exception:
                        pass
                    added.add(fd.name)

for sym in [
    "topcontrol.gamma.ps.core.statistics.StatisticService",
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.timetracking.TimeTrackingService",
]:
    add_sym(sym)

print("=" * 80)
print("EXPLORING TIME FILTER ENUMS AND DATE FIELDS")
print("=" * 80)

# Find all enum types related to time
for fn in sorted(added):
    try:
        fd = pool.FindFileByName(fn)
        for enum_type in fd.enum_types_by_name.values():
            name = enum_type.full_name
            if 'time' in name.lower() or 'filter' in name.lower() or 'period' in name.lower():
                print(f"\nENUM: {name}")
                for val in enum_type.values:
                    print(f"  {val.name} = {val.number}")
        
        for msg_type in fd.message_types_by_name.values():
            # Check nested enums
            for enum_type in msg_type.enum_types_by_name.values():
                name = enum_type.full_name
                if 'time' in name.lower() or 'filter' in name.lower() or 'period' in name.lower():
                    print(f"\nENUM (nested in {msg_type.full_name}): {name}")
                    for val in enum_type.values:
                        print(f"  {val.name} = {val.number}")
    except Exception as e:
        pass

# Explore the request messages for date/time fields
print("\n" + "=" * 80)
print("REQUEST MESSAGE FIELDS")
print("=" * 80)

req_messages = [
    "topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest",
    "topcontrol.gamma.ps.core.timetracking.GetLoginsRequest",
    "topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest",
]

def print_msg_fields(msg_name, indent=0):
    try:
        desc = pool.FindMessageTypeByName(msg_name)
        prefix = "  " * indent
        for field in desc.fields:
            type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
            print(f"{prefix}  [{field.number}] {field.name}: {type_name} (label={field.label})")
            if field.message_type and 'time' in field.name.lower() or (field.message_type and ('time' in field.message_type.full_name.lower() or 'date' in field.message_type.full_name.lower() or 'filter' in field.message_type.full_name.lower())):
                print_msg_fields(field.message_type.full_name, indent + 1)
    except Exception as e:
        print(f"  Error: {e}")

for msg in req_messages:
    print(f"\n{msg}:")
    print_msg_fields(msg)

# Deep dive into the AdHoc request for custom date fields
print("\n" + "=" * 80)
print("DEEP DIVE: GetWeighingReportDataAdHocRequest")
print("=" * 80)
try:
    desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest")
    for field in desc.fields:
        type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
        print(f"  [{field.number}] {field.name}: {type_name}")
        if field.message_type:
            sub_desc = field.message_type
            for sf in sub_desc.fields:
                st = sf.message_type.full_name if sf.message_type else sf.enum_type.full_name if sf.enum_type else sf.type
                print(f"    [{sf.number}] {sf.name}: {st}")
        if field.enum_type:
            for val in field.enum_type.values:
                print(f"    {val.name} = {val.number}")
except Exception as e:
    print(f"Error: {e}")

# Also look for GetLogins
print("\n" + "=" * 80)
print("DEEP DIVE: GetLoginsRequest")
print("=" * 80)
try:
    desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.timetracking.GetLoginsRequest")
    for field in desc.fields:
        type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
        print(f"  [{field.number}] {field.name}: {type_name}")
        if field.message_type:
            sub_desc = field.message_type
            for sf in sub_desc.fields:
                st = sf.message_type.full_name if sf.message_type else sf.enum_type.full_name if sf.enum_type else sf.type
                print(f"    [{sf.number}] {sf.name}: {st}")
        if field.enum_type:
            for val in field.enum_type.values:
                print(f"    {val.name} = {val.number}")
except Exception as e:
    print(f"Error: {e}")

# Look for StatisticService filter config
print("\n" + "=" * 80)
print("DEEP DIVE: GetWeighingStatisticDataRequest")
print("=" * 80)
try:
    desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.statistics.GetWeighingStatisticDataRequest")
    for field in desc.fields:
        type_name = field.message_type.full_name if field.message_type else field.enum_type.full_name if field.enum_type else field.type
        print(f"  [{field.number}] {field.name}: {type_name}")
        if field.message_type:
            sub_desc = field.message_type
            for sf in sub_desc.fields:
                st = sf.message_type.full_name if sf.message_type else sf.enum_type.full_name if sf.enum_type else sf.type
                print(f"    [{sf.number}] {sf.name}: {st}")
                if sf.message_type:
                    for ssf in sf.message_type.fields:
                        sst = ssf.message_type.full_name if ssf.message_type else ssf.enum_type.full_name if ssf.enum_type else ssf.type
                        print(f"      [{ssf.number}] {ssf.name}: {sst}")
                        if ssf.enum_type:
                            for val in ssf.enum_type.values:
                                print(f"        {val.name} = {val.number}")
                if sf.enum_type:
                    for val in sf.enum_type.values:
                        print(f"      {val.name} = {val.number}")
except Exception as e:
    print(f"Error: {e}")
