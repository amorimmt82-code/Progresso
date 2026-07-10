"""Deep dive into services that might have individual records with timestamps."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass
from google.protobuf import descriptor as _descriptor

GRPC_SERVER = "192.168.30.8:37270"
token = open(".token").read().strip()
meta = [("authorization", f"Bearer {token}")]

channel = grpc.insecure_channel(GRPC_SERVER)
stub = reflection_pb2_grpc.ServerReflectionStub(channel)

pool = DescriptorPool()
added = set()

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
                    except:
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
                    except:
                        pass
                    added.add(fd.name)

def print_message_schema(msg_desc, indent=0, seen=None):
    if seen is None:
        seen = set()
    if msg_desc.full_name in seen:
        print("  " * indent + f"(recursive ref to {msg_desc.name})")
        return
    seen.add(msg_desc.full_name)
    for field in msg_desc.fields:
        type_name = ""
        if field.type == field.TYPE_MESSAGE:
            type_name = field.message_type.name
        elif field.type == field.TYPE_ENUM:
            type_name = field.enum_type.name
            # Print enum values
            vals = ", ".join([f"{v.name}={v.number}" for v in field.enum_type.values])
            type_name += f" [{vals}]"
        else:
            type_names = {1:"double",2:"float",3:"int64",4:"uint64",5:"int32",
                8:"bool",9:"string",12:"bytes",13:"uint32",14:"enum",15:"sfixed32",
                16:"sfixed64",17:"sint32",18:"sint64"}
            type_name = type_names.get(field.type, f"type_{field.type}")
        
        label = ""
        if field.label == field.LABEL_REPEATED:
            label = "repeated "
        
        print("  " * indent + f"{label}{type_name} {field.name} = {field.number}")
        
        if field.type == field.TYPE_MESSAGE and indent < 3:
            print_message_schema(field.message_type, indent + 1, seen.copy())

# Load all interesting services
for svc in [
    "topcontrol.gamma.ps.core.analytics.ReportService",
    "topcontrol.gamma.ps.core.timetracking.TimeTrackingService",
    "topcontrol.gamma.ps.core.processing.ProcessService",
    "topcontrol.gamma.ps.core.monitoring.MonitoringService",
    "topcontrol.gamma.ps.core.traceability.TraceabilityService",
]:
    add_sym(svc)

# 1) Look at GetWeighingReportDataAdHocRequest schema
print("=" * 70)
print("GetWeighingReportDataAdHocRequest schema:")
print("=" * 70)
try:
    req_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataAdHocRequest")
    print_message_schema(req_desc)
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 70)
print("GetWeighingReportDataResponse schema:")
print("=" * 70)
try:
    resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetWeighingReportDataResponse")
    print_message_schema(resp_desc)
except Exception as e:
    print(f"ERROR: {e}")

# 2) GetLoginReportDataAdHocRequest schema 
print("\n" + "=" * 70)
print("GetLoginReportDataAdHocRequest schema:")
print("=" * 70)
try:
    req_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetLoginReportDataAdHocRequest")
    print_message_schema(req_desc)
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 70)
print("GetLoginReportDataResponse schema:")
print("=" * 70)
try:
    resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.analytics.GetLoginReportDataResponse")
    print_message_schema(resp_desc)
except Exception as e:
    print(f"ERROR: {e}")

# 3) TimeTrackingService methods
print("\n" + "=" * 70)
print("TimeTrackingService:")
print("=" * 70)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.timetracking.TimeTrackingService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
        print(f"  Request fields:")
        print_message_schema(m.input_type, indent=2)
except Exception as e:
    print(f"ERROR: {e}")

# 4) ProcessService methods  
print("\n" + "=" * 70)
print("ProcessService:")
print("=" * 70)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.processing.ProcessService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
except Exception as e:
    print(f"ERROR: {e}")

# 5) MonitoringService methods
print("\n" + "=" * 70)
print("MonitoringService:")
print("=" * 70)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.monitoring.MonitoringService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
        print(f"  Request fields:")
        print_message_schema(m.input_type, indent=2)
except Exception as e:
    print(f"ERROR: {e}")

# 6) TraceabilityService methods
print("\n" + "=" * 70)
print("TraceabilityService:")
print("=" * 70)
try:
    sd = pool.FindServiceByName("topcontrol.gamma.ps.core.traceability.TraceabilityService")
    for m in sd.methods:
        print(f"\n  {m.name}({m.input_type.name}) -> {m.output_type.name}")
except Exception as e:
    print(f"ERROR: {e}")

channel.close()
