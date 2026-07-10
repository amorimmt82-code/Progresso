"""Test OrderService for individual weighing records (punnets)."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2, empty_pb2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

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

add_sym("topcontrol.gamma.ps.core.orders.OrderService")

# ===== 1: Get Active Orders =====
print("=" * 60)
print("GetActiveOrders (Production)")
print("=" * 60)

try:
    Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetActiveOrdersRequest"))
    Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetActiveOrdersResponse"))
    
    req = Req()
    req.order_type_filter = 1  # PRODUCTION
    
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.orders.OrderService/GetActiveOrders",
        request_serializer=Req.SerializeToString,
        response_deserializer=Resp.FromString,
    )(req, metadata=meta)
    
    # Find the main repeated field
    resp_desc = resp.DESCRIPTOR
    fields = [f.name for f in resp_desc.fields]
    print(f"Response fields: {fields}")
    
    main_field = fields[0] if fields else None
    if main_field:
        items = getattr(resp, main_field)
        print(f"Got {len(items)} active orders")
        order_ids = []
        for i, order in enumerate(list(items)[:5]):
            oid = order.id.value if order.HasField("id") else "?"
            order_ids.append(oid)
            # Print a summary of the order
            print(f"\n--- Order {i+1}: {oid} ---")
            # Get field names
            ofields = [f.name for f in order.DESCRIPTOR.fields]
            for fn in ofields[:20]:
                val = getattr(order, fn, None)
                if val and str(val).strip():
                    s = str(val).strip()
                    if len(s) > 200:
                        s = s[:200] + "..."
                    print(f"  {fn}: {s}")
    
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")
    order_ids = []

# ===== 2: Get Closed Orders Today =====
print("\n" + "=" * 60)
print("GetClosedOrders (Production, TODAY)")
print("=" * 60)

try:
    Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetClosedOrdersRequest"))
    Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetClosedOrdersResponse"))
    
    req = Req()
    req.order_type_filter = 1  # PRODUCTION
    req.time_filter = 2  # TODAY
    
    resp = channel.unary_unary(
        "/topcontrol.gamma.ps.core.orders.OrderService/GetClosedOrders",
        request_serializer=Req.SerializeToString,
        response_deserializer=Resp.FromString,
    )(req, metadata=meta)
    
    resp_desc = resp.DESCRIPTOR
    fields = [f.name for f in resp_desc.fields]
    main_field = fields[0] if fields else None
    if main_field:
        items = getattr(resp, main_field)
        print(f"Got {len(items)} closed orders today")
        for i, order in enumerate(list(items)[:3]):
            oid = order.id.value if order.HasField("id") else "?"
            if oid not in order_ids:
                order_ids.append(oid)
            ofields = [f.name for f in order.DESCRIPTOR.fields]
            print(f"\n--- Order {i+1}: {oid} ---")
            for fn in ofields[:15]:
                val = getattr(order, fn, None)
                if val and str(val).strip():
                    s = str(val).strip()
                    if len(s) > 200:
                        s = s[:200] + "..."
                    print(f"  {fn}: {s}")
    
except grpc.RpcError as e:
    print(f"FAILED: {e.code()} - {e.details()}")

# ===== 3: GetOrderWeighingDetails for found orders =====
if order_ids:
    print("\n" + "=" * 60)
    print(f"GetOrderWeighingDetails for order {order_ids[0]}")
    print("=" * 60)

    try:
        Req = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsRequest"))
        Resp = GetMessageClass(pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsResponse"))
        
        # Print schema
        resp_desc = pool.FindMessageTypeByName("topcontrol.gamma.ps.core.orders.GetOrderWeighingDetailsResponse")
        print("Response schema:")
        for f in resp_desc.fields:
            label = "repeated " if f.label == f.LABEL_REPEATED else ""
            tname = f.message_type.name if f.type == f.TYPE_MESSAGE else f.type
            print(f"  {label}{f.name}: {tname}")
            if f.type == f.TYPE_MESSAGE:
                for sf in f.message_type.fields:
                    label2 = "repeated " if sf.label == sf.LABEL_REPEATED else ""
                    tname2 = sf.message_type.name if sf.type == sf.TYPE_MESSAGE else sf.type
                    print(f"    {label2}{sf.name}: {tname2}")
        
        req = Req()
        uid = req.order_ids.add()
        uid.value = order_ids[0]
        
        resp = channel.unary_unary(
            "/topcontrol.gamma.ps.core.orders.OrderService/GetOrderWeighingDetails",
            request_serializer=Req.SerializeToString,
            response_deserializer=Resp.FromString,
        )(req, metadata=meta)
        
        resp_fields = [f.name for f in resp.DESCRIPTOR.fields]
        print(f"\nResponse fields: {resp_fields}")
        main_field = resp_fields[0] if resp_fields else None
        if main_field:
            items = getattr(resp, main_field)
            print(f"Got {len(items)} items")
            for i, item in enumerate(list(items)[:10]):
                print(f"\n--- Weighing {i+1} ---")
                print(item)
        
    except grpc.RpcError as e:
        print(f"FAILED: {e.code()} - {e.details()}")
else:
    print("\nNo orders found to query weighing details")

channel.close()
