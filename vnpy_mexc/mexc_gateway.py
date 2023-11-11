import json
import hmac
import sys
from copy import copy
from datetime import datetime, timedelta
from time import time,sleep
from threading import Lock
from typing import Dict, List, Any,Union
import requests

from vnpy.event import Event,EventEngine
from vnpy_rest import RestClient, Request
from vnpy_websocket import WebsocketClient
from types import coroutine
from asyncio import (
    run_coroutine_threadsafe,
)
from vnpy.trader.constant import (
    Direction,
    Offset,
    Exchange,
    Product,
    Status,
    OrderType,
    Interval
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    TickData,
    OrderData,
    TradeData,
    BarData,
    AccountData,
    PositionData,
    ContractData,
    OrderRequest,
    CancelRequest,
    SubscribeRequest,
    HistoryRequest
)
from vnpy.trader.event import EVENT_TIMER
from vnpy.trader.utility import round_to,ZoneInfo


# 中国时区
CHINA_TZ = ZoneInfo("Asia/Shanghai")

REST_HOST = "https://contract.mexc.com"
WEBSOCKET_DATA_HOST = "wss://contract.mexc.com/ws"               # Market Data
WEBSOCKET_TRADE_HOST = "wss://contract.mexc.com/ws"    # Account and Order

STATUS_MEXC2VT: Dict[int, Status] = {
    1: Status.NOTTRADED,
    2: Status.NOTTRADED,
    4: Status.CANCELLED,
    5: Status.CANCELLED,
    3: Status.ALLTRADED,
}

PLANSTATUS_MEXC2VT: Dict[int, Status] = {
    1: Status.NOTTRADED,
    3:Status.ALLTRADED,
    5: Status.REJECTED,
    2: Status.CANCELLED,
    4: Status.CANCELLED,
    
}

ORDERTYPE_VT2MEXC: Dict[OrderType, Any] = {
    OrderType.LIMIT: 1,
    OrderType.MARKET: 5,
}
ORDERTYPE_MEXC2VT: Dict[Any, OrderType] = {v: k for k, v in ORDERTYPE_VT2MEXC.items()}

DIRECTION_VT2MEXC: Dict[Direction, Any] = {
    Direction.LONG: 1,
    Direction.SHORT: 3
}
DIRECTION_MEXC2VT: Dict[Any, Direction] = {v: k for k, v in DIRECTION_VT2MEXC.items()}

DIRECTION_MEXC2VT: Dict[Any, Direction] = {
    1:Direction.LONG,
    2:Direction.SHORT,
    3:Direction.SHORT,
    4:Direction.LONG
}

HOLDSIDE_MEXC2VT: Dict[Any,Direction] = {
    1:Direction.LONG,
    2:Direction.SHORT
}

INTERVAL_VT2MEXC: Dict[Interval, str] = {
    Interval.MINUTE: "Min1",
    Interval.HOUR: "Min60",
    Interval.DAILY: "Day1"
}

TIMEDELTA_MAP: Dict[Interval, timedelta] = {
    Interval.MINUTE: timedelta(minutes=1),
    Interval.HOUR: timedelta(hours=1),
    Interval.DAILY: timedelta(days=1),
}

# 合约数据全局缓存字典
symbol_contract_map: Dict[str, ContractData] = {}


class MexcGateway(BaseGateway):
    """
    * mexc接口
    * 单向持仓模式
    """
    
    default_name: str = "MEXC_USDT"

    default_setting: Dict[str, Any] = {
        "Access Key": "",
        "Secret Key": "",
        "代理地址": "",
        "代理端口": "",
    }

    exchanges = [Exchange.MEXC]        #由main_engine add_gateway调用
    #------------------------------------------------------------------------------------------------- 
    def __init__(self, event_engine: EventEngine, gateway_name: str):
        """
        """
        super(MexcGateway,self).__init__(event_engine, gateway_name)
        self.orders: Dict[str, OrderData] = {}
        self.rest_api = MexcRestApi(self)
        self.trade_ws_api = MexcTradeWebsocketApi(self)
        self.market_ws_api = MexcDataWebsocketApi(self)
        self.count = 0  #轮询计时:秒
    #------------------------------------------------------------------------------------------------- 
    def connect(self,setting:dict = {}):
        """
        """

        key = setting["Access Key"]
        secret = setting["Secret Key"]
        proxy_host = setting["代理地址"]
        proxy_port = setting["代理端口"]

        self.rest_api.connect(key, secret,proxy_host, proxy_port)
        self.trade_ws_api.connect(key, secret, proxy_host, proxy_port)
        self.market_ws_api.connect(key, secret, proxy_host, proxy_port)

        self.init_query()
    #------------------------------------------------------------------------------------------------- 
    def subscribe(self, req: SubscribeRequest) -> None:
        """
        订阅合约
        """
        self.market_ws_api.subscribe(req)
    #------------------------------------------------------------------------------------------------- 
    def send_order(self, req: OrderRequest) -> str:
        """
        发送委托单
        """
        return self.rest_api.send_order(req)
    #------------------------------------------------------------------------------------------------- 
    def cancel_order(self, req: CancelRequest) -> Request:
        """
        取消委托单
        """
        self.rest_api.cancel_order(req)
    #------------------------------------------------------------------------------------------------- 
    def query_account(self) -> Request:
        """
        查询账户
        """
        self.rest_api.query_account()
    #------------------------------------------------------------------------------------------------- 
    def query_order(self,symbol:str):
        """
        查询活动委托单
        """
        self.rest_api.query_order(symbol)
    #-------------------------------------------------------------------------------------------------  
    def query_position(self, symbol: str):
        """
        查询持仓
        """
        pass
    #-------------------------------------------------------------------------------------------------   
    def query_history(self, req: HistoryRequest) -> List[BarData]:
        """查询历史数据"""
        return self.rest_api.query_history(req)
    #---------------------------------------------------------------------------------------
    def on_order(self, order: OrderData) -> None:
        """
        收到委托单推送，BaseGateway推送数据
        """
        self.orders[order.orderid] = copy(order)
        super().on_order(order)
    #---------------------------------------------------------------------------------------
    def get_order(self, orderid: str) -> OrderData:
        """
        用vt_orderid获取委托单数据
        """
        return self.orders.get(orderid, None)
    #------------------------------------------------------------------------------------------------- 
    def close(self) -> None:
        """
        关闭接口
        """
        self.rest_api.stop()
        self.trade_ws_api.stop()
        self.market_ws_api.stop()
    #------------------------------------------------------------------------------------------------- 
    def process_timer_event(self, event: Event):
        """
        处理定时任务
        """
        pass
    #------------------------------------------------------------------------------------------------- 
    def init_query(self):
        """
        初始化定时查询
        """
        self.event_engine.register(EVENT_TIMER, self.process_timer_event)
#------------------------------------------------------------------------------------------------- 
class MexcRestApi(RestClient):
    """
    Mexc REST API
    """
    def __init__(self, gateway: MexcGateway):
        """
        """
        super().__init__()

        self.gateway = gateway
        self.gateway_name: str = gateway.gateway_name

        self.host: str = ""
        self.key: str = ""
        self.secret: str = ""

        self.order_count: int = 10000
        self.order_count_lock: Lock = Lock()
        self.connect_time: int = 0

        self.contract_inited:bool = False
    #------------------------------------------------------------------------------------------------- 
    def sign(self, request) -> Request:
        """
        生成签名
        """
        timestamp = str(int(time() * 1000))

        method = request.method
        data = request.data
        params = request.params
        if method == "GET":
            body = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        elif method == "POST":
            body = request.data = json.dumps(data)
        else:
            body = ""
        
        message = self.key + timestamp + body
        signature = create_signature(self.secret,message)

        if not request.headers:
            request.headers = {}
            request.headers["ApiKey"] = self.key
            request.headers["Signature"] = signature
            request.headers["Request-Time"] = timestamp
            request.headers["Content-Type"] = "application/json"
        return request
    #------------------------------------------------------------------------------------------------- 
    def connect(
        self,
        key: str,
        secret: str,
        proxy_host: str,
        proxy_port: int
    ) -> None:
        """
        连接REST服务
        """
        self.key = key
        self.secret = secret
        self.connect_time = (
            int(datetime.now().strftime("%y%m%d%H%M%S")) * self.order_count
        )

        self.init(REST_HOST, proxy_host, proxy_port)
        self.start()

        self.gateway.write_log(f"交易接口：{self.gateway_name}，REST API启动成功")

        self.query_contract()
        self.query_account()
        self.query_order()
    #------------------------------------------------------------------------------------------------- 
    def set_leverage(self,symbol:str):
        """
        设置杠杆
        """
        
        data = {
            "symbol":symbol,
            "leverage":20,
        }
        self.add_request(
            method="POST",
            path="/api/v1/private/position/change_leverage",
            callback=self.on_leverage,
            data = data
        )
    #------------------------------------------------------------------------------------------------- 
    def on_leverage(self,data:dict,request: Request):
        pass
    #------------------------------------------------------------------------------------------------- 
    def query_account(self) -> Request:
        """
        查询账户数据
        """
        params = {}
        self.add_request(
            method="GET",
            path="/api/v1/private/account/assets",
            callback=self.on_query_account,
            params= params
        )
    #------------------------------------------------------------------------------------------------- 
    def query_order(self):
        """
        查询合约活动委托单
        """
        params = {
            "page_num":1,
            "page_size":20
            }
        self.add_request(
            method="GET",
            path="/api/v1/private/order/list/open_orders",
            callback=self.on_query_order,
            params=params
        )
        self.add_request(
            method="GET",
            path="/api/v1/private/planorder/list/orders",
            callback=self.on_query_order_Algo,
            params=params
        )

    #------------------------------------------------------------------------------------------------- 
    def query_contract(self) -> Request:
        """
        获取合约信息
        """
        params = {}    
        self.add_request(
            method="GET",
            path="/api/v1/contract/detail",
            params = params,
            callback=self.on_query_contract,
        )
    #------------------------------------------------------------------------------------------------- 
    def query_history(self, req: HistoryRequest) -> List[BarData]:
        """
        查询历史数据
        """
        history : List[BarData] = []
        limit: int = 2000

        start_time: int = int(datetime.timestamp(req.start))
        stop_time = int(datetime.timestamp(req.end))
        while True:
            
            # 查询K线参数
            params = {
                "symbol": req.symbol,
                "interval": INTERVAL_VT2MEXC[req.interval],
                "start": start_time,
            }

            resp = self.request(
                "GET",
                f"/api/v1/contract/kline/{req.symbol}",
                params=params
            )
            
            # resp为空或收到错误代码则跳出循环
            if not resp:
                msg = f"获取历史数据失败，状态码：{resp}"
                self.gateway.write_log(msg)
                break
            elif resp.status_code // 100 != 2:
                msg = f"获取历史数据失败，状态码：{resp.status_code}，信息：{resp.text}"
                self.gateway.write_log(msg)
                break
            else:
                rawdata = resp.json()
                if not rawdata:
                    msg: str = f"获取历史数据为空，开始时间：{start_time}"
                    self.gateway.write_log(msg)
                    break

                buf: List[BarData] = []
                data=rawdata["data"]
                for index, _ in enumerate(data["time"]):

                    dt = get_local_datetime(int(data["time"][index]) * 1000)

                    bar = BarData(
                        symbol=req.symbol,
                        exchange=req.exchange,
                        datetime=dt,
                        interval=req.interval,
                        volume=float(data["vol"][index]),
                        open_price=float(data["open"][index]),
                        high_price=float(data["high"][index]),
                        low_price=float(data["low"][index]),
                        close_price=float(data["close"][index]),
                        gateway_name=self.gateway_name
                    )
                    buf.append(bar)

                history.extend(buf)
                
                begin_time: datetime = buf[0].datetime
                end_time: datetime = buf[-1].datetime

                msg: str = f"获取历史数据成功，{req.symbol} - {req.interval.value}，{begin_time} - {end_time}"
                self.gateway.write_log(msg)

                
                # 如果收到了最后一批数据则终止循环
                if len(data["time"]) < limit:
                    break

                #if start_time>stop_time:
                #    break

                # 更新开始时间
                start_dt = bar.datetime + TIMEDELTA_MAP[req.interval]
                start_time = int(datetime.timestamp(start_dt))
        return history
    #------------------------------------------------------------------------------------------------- 
    def new_local_orderid(self) -> str:
        """
        生成local_orderid
        """
        with self.order_count_lock:
            self.order_count += 1
            local_orderid = str(self.connect_time+self.order_count)
            return local_orderid
    #------------------------------------------------------------------------------------------------- 
    def send_order(self, req: OrderRequest) -> str:
        """
        发送委托单
        """
        #api不可用
        rest_host="http://localhost:5102"
        DIRECTION2STR = {
            Direction.LONG:"long",
            Direction.SHORT:"short"
        }
        #local_orderid =req.symbol + "-" + self.new_local_orderid()
        
        if req.type==OrderType.STOP:
            '''
            data = {
                "symbol": req.symbol,
                "triggerPrice": str(req.price),
                "triggerType":1 if req.direction==Direction.LONG else 2,
                "vol": str(req.volume),
                "side": DIRECTION_VT2MEXC.get(req.direction),
                "openType":2,
                "executeCycle":1,
                "orderType": ORDERTYPE_VT2MEXC.get(OrderType.MARKET),
                "trend":1
            }
            self.add_request(
                method="POST",
                path=#"/api/v1/private/planorder/place",
                callback=self.on_send_order,
                data=data,
                extra=order,
                on_error=self.on_send_order_error,
                on_failed=self.on_send_order_failed
            )
            '''
            tp=-1
            sl=-1
            data = {
            'direction': DIRECTION2STR[req.direction],
            'trigger_price': float(req.price),
            'quantity': float(req.volume),
            'take_profit_price': tp,
            'stop_loss_price': sl
            }
            response=requests.post(f'{rest_host}/place_stop_order', json=data)
            try:
                res=json.loads(response.json())
                orderid=res["data"]
            except:
                self.cancel_all()
                return False
        elif req.type == OrderType.MARKET:
            data = {
            'direction': DIRECTION2STR[req.direction],
            'quantity': float(req.volume)
            }
            response=requests.post(f'{rest_host}/place_market_order', json=data)
            try:
                res=json.loads(response.json())
                orderid=res["data"]["orderId"]
            except:
                self.cancel_all()
                return False
        else:
            '''
            data = {
                "symbol": req.symbol,
                "price": float(req.price),
                "vol": float(req.volume),
                "side": DIRECTION_VT2MEXC.get(req.direction),
                "type": ORDERTYPE_VT2MEXC.get(req.type),
                "openType": 2,
            }

            if req.offset == Offset.CLOSE:
                data["reduceOnly"] = True

            self.add_request(
                method="POST",
                path="/api/v1/private/order/submit",
                callback=self.on_send_order,
                data=data,
                extra=order,
                on_error=self.on_send_order_error,
                on_failed=self.on_send_order_failed
            )
            '''
            data = {
            'direction': DIRECTION2STR[req.direction],
            'price': float(req.price),
            'quantity': float(req.volume)
            }
            response=requests.post(f'{rest_host}/place_limit_order', json=data)
            try:
                res=json.loads(response.json())
                orderid=res["data"]["orderId"]
            except:
                self.cancel_all()
                return False
        order = req.create_order_data(
            orderid,
            self.gateway_name
        )
        print(orderid)
        self.gateway.on_order(order)
        return order.vt_orderid
    #------------------------------------------------------------------------------------------------- 
    def cancel_order(self, req: CancelRequest) -> Request:
        """
        取消委托单
        """
        order: OrderData = self.gateway.get_order(req.orderid)
        #计划委托单撤单
        if order.type==OrderType.STOP:
            data = [
                {
                    "symbol" : req.symbol,
                    "orderId" : req.orderid
                }
            ]
            self.add_request(
                method="POST",
                path="/api/v1/private/planorder/cancel",
                callback=self.on_cancel_order,
                on_failed=self.on_cancel_order_failed,
                data=data,
                extra=order
            )
        #普通委托单撤单
        else:
            data = [
                int(req.orderid)
            ]
            self.add_request(
                method="POST",
                path="/api/v1/private/order/cancel",
                callback=self.on_cancel_order,
                on_failed=self.on_cancel_order_failed,
                data=data,
                extra=order
            )
    def cancel_all(self) -> Request:
        """
        取消全部委托单
        """
        #计划委托单撤单
        data ={}
        self.add_request(
            method="POST",
            path="/api/v1/private/planorder/cancel_all",
            callback=self.on_cancel_order,
            on_failed=self.on_cancel_order_failed,
            data=data,
            extra=None
        )
        #普通委托单撤单
        data = {}
        self.add_request(
            method="POST",
            path="/api/v1/private/order/cancel_all",
            callback=self.on_cancel_order,
            on_failed=self.on_cancel_order_failed,
            data=data,
            extra=None
        )
    #------------------------------------------------------------------------------------------------- 
    def on_query_account(self, data: dict, request: Request) -> None:
        """
        收到账户数据回报
        """
        if self.check_error(data, "查询账户"):
            return
        for account_data in data["data"]:
            account = AccountData(
                accountid=account_data["currency"] + "_" + self.gateway_name,
                balance= float(account_data["availableBalance"]),
                frozen=float(account_data["frozenBalance"]),
                gateway_name=self.gateway_name,
            )
            if account.balance:
                self.gateway.on_account(account)
                
        self.gateway.write_log("账户资金查询成功")

    #------------------------------------------------------------------------------------------------- 
    def on_query_order(self, data: dict, request: Request) -> None:
        """
        收到委托回报
        """

        if self.check_error(data, "查询活动委托"):
            return
        data = data["data"]
        if not data:
            return
        for order_data in data:
            order_datetime =  get_local_datetime(int(order_data["createTime"]))

            order = OrderData(
                orderid=order_data["orderId"],
                symbol=order_data["symbol"],
                exchange=Exchange.MEXC,
                price=order_data["price"],
                volume=order_data["vol"],
                type=ORDERTYPE_MEXC2VT[order_data["orderType"]],
                direction=DIRECTION_MEXC2VT[order_data["side"]],
                traded=float(order_data["dealVol"]),
                status=STATUS_MEXC2VT[order_data["state"]],
                datetime= order_datetime,
                gateway_name=self.gateway_name,
            )

            self.gateway.on_order(order)

        self.gateway.write_log("当前委托信息查询成功")
    def on_query_order_Algo(self, data: dict, request: Request) -> None:
        """
        收到委托回报
        """

        if self.check_error(data, "查询活动委托"):
            return
        data = data["data"]
        if not data:
            return
        for order_data in data:
            order_datetime =  get_local_datetime(int(order_data["createTime"]))

            order = OrderData(
                orderid=order_data["id"],
                symbol=order_data["symbol"],
                exchange=Exchange.MEXC,
                price=order_data["triggerPrice"],
                volume=order_data["vol"],
                type=OrderType.STOP,
                direction=DIRECTION_MEXC2VT[order_data["side"]],
                traded=0.0,
                status=PLANSTATUS_MEXC2VT[order_data["state"]],
                datetime= order_datetime,
                gateway_name=self.gateway_name,
            )
            self.gateway.on_order(order)

        self.gateway.write_log("计划委托信息查询成功")
    #------------------------------------------------------------------------------------------------- 
    def on_query_contract(self, data: dict, request: Request) -> None:
        """
        收到合约参数回报
        """
        if self.check_error(data, "查询合约"):
            return
        for contract_data in data["data"]:
            price_place = contract_data["priceScale"]
            contract = ContractData(
                symbol=contract_data["symbol"],
                exchange=Exchange.MEXC,
                name=contract_data["displayName"],
                #pricetick=float(contract_data["priceUnit"]) * float(f"1e-{price_place}"),
                pricetick=float(contract_data["priceUnit"]),
                size=20,    # 合约杠杆
                min_volume=float(contract_data["minVol"]) * float(contract_data["priceUnit"]),
                product=Product.FUTURES,
                net_position=True,
                history_data=True,
                gateway_name=self.gateway_name,
                stop_supported=True
            )

            self.gateway.on_contract(contract)

            symbol_contract_map[contract.symbol] = contract


        product_type = contract_data["quoteCoin"]
        self.gateway.write_log(f"交易接口：{self.gateway_name}，{product_type}合约信息查询成功")
        self.contract_inited = True
    #------------------------------------------------------------------------------------------------- 
    def on_send_order(self, data: dict, request: Request) -> None:
        """
        """
        order = request.extra

        if self.check_error(data, "委托"):
            order.status = Status.REJECTED
            self.gateway.on_order(order)
    #------------------------------------------------------------------------------------------------- 
    def on_send_order_failed(self, status_code, request: Request) -> None:
        """
        收到委托失败回报
        """
        order = request.extra
        order.status = Status.REJECTED
        self.gateway.on_order(order)

        msg = f"委托失败，状态码：{status_code}，信息：{request.response.text}"
        self.gateway.write_log(msg)
    #------------------------------------------------------------------------------------------------- 
    def on_send_order_error(
        self,
        exception_type: type,
        exception_value: Exception,
        tb,
        request: Request
    ):
        """
        Callback when sending order caused exception.
        """
        order = request.extra
        order.status = Status.REJECTED
        self.gateway.on_order(order)

        # Record exception if not ConnectionError
        if not issubclass(exception_type, ConnectionError):
            self.on_error(exception_type, exception_value, tb, request)
    #------------------------------------------------------------------------------------------------- 
    def on_cancel_order(self, data: dict, request: Request) -> None:
        """
        """
        self.check_error(data, "撤单")
    #------------------------------------------------------------------------------------------------- 
    def on_cancel_order_failed(
        self,
        status_code,
        request: Request
    ) -> None:
        """
        收到撤单失败回报
        """
        if request.extra:
            order = request.extra
            order.status = Status.REJECTED
            self.gateway.on_order(order)
        msg = f"撤单失败，状态码：{status_code}，信息：{request.response.text}"
        self.gateway.write_log(msg)
    #------------------------------------------------------------------------------------------------- 
    def on_error(
        self,
        exception_type: type,
        exception_value: Exception,
        tb,
        request: Request
    ) -> None:
        """
        Callback to handler request exception.
        """
        msg = f"触发异常，状态码：{exception_type}，信息：{exception_value}"
        self.gateway.write_log(msg)

        sys.stderr.write(
            self.exception_detail(exception_type, exception_value, tb, request)
        )
    #------------------------------------------------------------------------------------------------- 
    def check_error(self, data: dict, func: str = "") -> bool:
        """
        """
        if data["success"] == True:
            return False

        error_code = data["code"]
        error_msg = data["message"]
        self.gateway.write_log(f"{func}请求出错，代码：{error_code}，信息：{error_msg}")
        return True

#------------------------------------------------------------------------------------------------- 
class MexcWebsocketApiBase(WebsocketClient):
    """
    """

    def __init__(self, gateway):
        """
        """
        super(MexcWebsocketApiBase, self).__init__()

        self.gateway: MexcGateway = gateway
        self.gateway_name: str = gateway.gateway_name

        self.key: str = ""
        self.secret: str = ""
        self.passphrase: str = ""
        self.count = 0

    def send_packet(self, packet: dict):
        """
        发送数据包字典到服务器。

        如果需要发送非json数据，请重载实现本函数。
        """
        if self._ws:
            if packet in ["pong","ping"]:
                text = packet
            else:
                text: str = json.dumps(packet)
            self._record_last_sent_text(text)

            coro: coroutine = self._ws.send_str(text)
            run_coroutine_threadsafe(coro, self._loop)
    def unpack_data(self, data: str):
        """
        对字符串数据进行json格式解包

        如果需要使用json以外的解包格式，请重载实现本函数。
        """
        if data in ["pong","ping"]:
            return data
        else:
            return json.loads(data)
    #------------------------------------------------------------------------------------------------- 
    def connect(
        self,
        key: str,
        secret: str,
        url: str,
        proxy_host: str,
        proxy_port: int
    ) -> None:
        """
        """
        self.key = key
        self.secret = secret

        self.init(url, proxy_host, proxy_port)
        self.start()
        self.gateway.event_engine.register(EVENT_TIMER,self.send_ping)
    #------------------------------------------------------------------------------------------------- 
    def send_ping(self,event):
        self.count +=1
        if self.count < 15:
            return
        self.count = 0
        message={
            "method": "ping"
        }
        self.send_packet(message)
    #------------------------------------------------------------------------------------------------- 
    def login(self) -> int:
        """
        """
        timestamp = str(int(time()))

        #message = self.key+ 'GET' + timestamp
        message = self.key + timestamp
        signature = create_signature(self.secret,message)
        params = {
            "method":"login",
            "param":{
                "apiKey":self.key,
                "reqTime":timestamp,
                "signature":signature
            }
        }
        return self.send_packet(params)
    #------------------------------------------------------------------------------------------------- 
    def on_login(self, packet) -> None:
        """
        """
        pass
    #------------------------------------------------------------------------------------------------- 
    def on_data(self, packet):
        pass
    #------------------------------------------------------------------------------------------------- 
    def on_packet(self, packet:Union[str,dict]) -> None:
        """
        """
        if packet["channel"] == "pong":
            return
        if packet["channel"] == "rs.login" and packet["data"] == "success":
            self.on_login()
        elif packet["channel"] == "rs.error":
            self.on_error_msg(packet)
        else:
            self.on_data(packet)
    #------------------------------------------------------------------------------------------------- 
    def on_error_msg(self, packet) -> None:
        """
        """
        msg = packet["data"]
        self.gateway.write_log(f"交易接口：{self.gateway_name} WebSocket API收到错误回报，回报信息：{msg}")
#------------------------------------------------------------------------------------------------- 
class MexcDataWebsocketApi(MexcWebsocketApiBase):
    """
    """

    def __init__(self, gateway: MexcGateway):
        """
        """
        super().__init__(gateway)

        self.ticks:Dict[str,TickData] = {}
    #------------------------------------------------------------------------------------------------- 
    def connect(
        self,
        key: str,
        secret: str,
        proxy_host: str,
        proxy_port: int
    ) -> None:
        """
        """
        super().connect(
            key,
            secret,
            WEBSOCKET_DATA_HOST,
            proxy_host,
            proxy_port
        )
    #------------------------------------------------------------------------------------------------- 
    def on_connected(self) -> None:
        """
        """
        self.gateway.write_log(f"行情接口：{self.gateway_name}，行情Websocket API连接成功")

    #-------------------------------------------------------------------------------------------------
    def on_disconnected(self):
        """
        ws行情断开回调
        """
        self.gateway.write_log(f"行情接口：{self.gateway_name}，行情Websocket API连接断开")
    #------------------------------------------------------------------------------------------------- 
    def subscribe(self, req: SubscribeRequest) -> None:
        """
        订阅合约
        """
        # 等待rest合约数据推送完成再订阅
        while not self.gateway.rest_api.contract_inited:
            sleep(1)

        if req.symbol in self.ticks:
            return
        
        if req.symbol not in symbol_contract_map:
            self.gateway.write_log(f"找不到该合约代码{req.symbol}")
            return
        
        tick = TickData(
            symbol=req.symbol,
            name=symbol_contract_map[req.symbol].name,
            exchange=Exchange.MEXC,
            datetime=datetime.now(CHINA_TZ),
            gateway_name=self.gateway_name,
        )

        self.ticks[req.symbol] = tick

        msg: dict = {
            "method":"sub.ticker",
            "param":{
                "symbol":req.symbol
            }
        }
        self.send_packet(msg)

        msg: dict = {
            "method":"sub.depth.full",
            "param":{
                "symbol":req.symbol,
                "limit":5
            }
        }
        self.send_packet(msg)
    #------------------------------------------------------------------------------------------------- 
    def on_data(self, packet) -> None:
        """
        """
        channel = packet["channel"]
        if channel == "push.ticker":
            self.on_tick(packet["data"])
        elif channel == "push.depth.full":
            self.on_depth(packet)
    #------------------------------------------------------------------------------------------------- 
    def on_tick(self, data: dict) -> None:
        """
        收到tick数据推送
        """
        
        tick: TickData = self.ticks[data["symbol"]]

        tick.volume = float(data['volume24'])
        tick.high_price = float(data["high24Price"])
        tick.low_price = float(data["lower24Price"])
        tick.last_price = float(data["lastPrice"])
        tick.datetime = get_local_datetime(data["timestamp"])
        tick.bid_price_1 = float(data["bid1"])
        tick.ask_price_1 = float(data["ask1"])
        tick.open_interest = float(data["holdVol"])

        if tick.last_price:
            tick.localtime = datetime.now()
            self.gateway.on_tick(copy(tick))
    #------------------------------------------------------------------------------------------------- 
    def on_depth(self, data: dict) -> None:
        """
        行情深度推送
        """
        tick: TickData = self.ticks[data["symbol"]]

        tick.datetime = get_local_datetime(int(data["ts"]))
        data_=data["data"]

        bids = data_["bids"]
        asks = data_["asks"]
        for index in range(len(bids)):
            price, volume , ordercount = bids[index]
            tick.__setattr__("bid_price_" + str(index + 1), float(price))
            tick.__setattr__("bid_volume_" + str(index + 1), float(volume))

        for index in range(len(asks)):
            price, volume , ordercount = asks[index]
            tick.__setattr__("ask_price_" + str(index + 1), float(price))
            tick.__setattr__("ask_volume_" + str(index + 1), float(volume))

        if tick.last_price:
            self.gateway.on_tick(copy(tick))
    
#------------------------------------------------------------------------------------------------- 
class MexcTradeWebsocketApi(MexcWebsocketApiBase):
    """
    """
    def __init__(self, gateway: MexcGateway):
        """
        """
        self.trade_count = 0
        super().__init__(gateway)
    #------------------------------------------------------------------------------------------------- 
    def connect(
        self,
        key: str,
        secret: str,
        proxy_host: str,
        proxy_port: int
    ) -> None:
        """
        """
        super().connect(
            key,
            secret,
            WEBSOCKET_TRADE_HOST,
            proxy_host,
            proxy_port
        )
    #------------------------------------------------------------------------------------------------- 
    def subscribe_private(self) -> int:
        """
        订阅私有频道
        """
        #登陆后会自动推送，不再需要订阅
        pass
    #------------------------------------------------------------------------------------------------- 
    def on_connected(self) -> None:
        """
        """
        self.gateway.write_log(f"交易接口：{self.gateway_name}，交易Websocket API连接成功")
        self.login()
    #-------------------------------------------------------------------------------------------------
    def on_disconnected(self):
        """
        ws交易断开回调
        """
        self.gateway.write_log(f"交易接口：{self.gateway_name}，交易Websocket API连接断开")
    #------------------------------------------------------------------------------------------------- 
    def on_login(self) -> None:
        """
        """
        self.gateway.write_log(f"交易接口：{self.gateway_name}，交易Websocket API登录成功")
        self.subscribe_private()
    #------------------------------------------------------------------------------------------------- 
    def on_packet(self, packet:Union[str,dict]) -> None:
        """
        """
        if packet["channel"] == "pong":
            return
        if packet["channel"] == "rs.login" and packet["data"] == "success":
            self.on_login()
        elif packet["channel"] == "rs.error":
            self.on_error_msg(packet)
        else:
            self.on_data(packet)
        ######在日志显示所有ws包
        self.gateway.write_log(packet)
        ########################
    def on_data(self, data) -> None:
        """
        """
        channel = data["channel"]
        if channel == "push.personal.position":
            self.on_position(data)
        elif channel == "push.personal.order":
            self.on_order(data)
        elif channel == "push.personal.plan.order":
            self.on_plan_order(data)
        elif channel == "push.personal.stop.planorder":
            self.on_stop_plan_order(data)
    #------------------------------------------------------------------------------------------------- 
    def on_order(self, raw: dict) -> None:
        """
        收到委托回报
        """
        data=raw["data"]
        
        if STATUS_MEXC2VT[data["state"]]==Status.ALLTRADED:
            price=float(data["dealAvgPrice"])
        else:
            price=float(data["price"])
        order_datetime = get_local_datetime(data["createTime"])
        orderid = data["orderId"]
        offset = self.gateway.get_order(orderid).offset if self.gateway.get_order(orderid) else None
        order = OrderData(
            symbol=data["symbol"],
            exchange=Exchange.MEXC,
            orderid=orderid,
            type=ORDERTYPE_MEXC2VT[data["orderType"]],
            direction=DIRECTION_MEXC2VT[data["side"]],
            price=price,
            volume=float(data["vol"]),
            traded=float(data["dealVol"]),
            status=STATUS_MEXC2VT[data["state"]],
            datetime = order_datetime,
            gateway_name=self.gateway_name,
            offset=offset
        )
        self.gateway.on_order(order)

        # 将成交数量四舍五入到正确精度
        trade_volume: float = float(data["dealVol"])
        contract: ContractData = symbol_contract_map.get(order.symbol, None)
        if contract:
            trade_volume = round_to(trade_volume, contract.min_volume)
        if not trade_volume:
            return
        
        self.trade_count += 1

        trade = TradeData(
            symbol=order.symbol,
            exchange=Exchange.MEXC,
            orderid=order.orderid,
            tradeid=str(self.trade_count),
            direction=order.direction,
            offset=offset,
            price=float(data["dealAvgPrice"]),
            volume=float(data["dealVol"]),
            datetime= get_local_datetime(int(data["updateTime"])),
            gateway_name=self.gateway_name,
        )
        self.gateway.on_trade(trade)

    def on_plan_order(self, raw: dict) -> None:
        """
        收到委托回报
        """
        data=raw["data"]
        
        if PLANSTATUS_MEXC2VT[data["state"]]==Status.ALLTRADED:
            traded=float(data["vol"])
            price=float(data["triggerPrice"])
        elif data["state"] == 1:
            #1表示new
            return
        else:
            traded=0
            price=float(data["triggerPrice"])
        order_datetime = get_local_datetime(data["createTime"])
        orderid = data["id"]
        offset = self.gateway.get_order(orderid).offset if self.gateway.get_order(orderid) else None
        order = OrderData(
            symbol=data["symbol"],
            exchange=Exchange.MEXC,
            orderid=orderid,
            type=OrderType.STOP,
            direction=DIRECTION_MEXC2VT[data["side"]],
            price=price,
            volume=float(data["vol"]),
            traded=traded,
            status=PLANSTATUS_MEXC2VT[data["state"]],
            datetime = order_datetime,
            gateway_name=self.gateway_name,
            offset=offset
        )
        self.gateway.on_order(order)

        # 将成交数量四舍五入到正确精度
        trade_volume: float = float(data["vol"])
        contract: ContractData = symbol_contract_map.get(order.symbol, None)
        if contract:
            trade_volume = round_to(trade_volume, contract.min_volume)
        if order.traded == 0:
            return
        
        self.trade_count += 1

        trade = TradeData(
            symbol=order.symbol,
            exchange=Exchange.MEXC,
            orderid=order.orderid,
            tradeid=str(self.trade_count),
            direction=order.direction,
            offset=order.offset,
            price=float(data["triggerPrice"]),
            volume=float(data["vol"]),
            datetime= get_local_datetime(int(data["updateTime"])),
            gateway_name=self.gateway_name,
        )
        self.gateway.on_trade(trade)

    def on_stop_plan_order(self, raw: dict) -> None:
        """
        收到委托回报
        """
        data=raw["data"]
        
        if PLANSTATUS_MEXC2VT[data["state"]]==Status.ALLTRADED:
            traded=float(data["vol"])
            price=float(data["triggerPrice"])
        else:
            traded=0
            price=float(data["triggerPrice"])
        order_datetime = get_local_datetime(data["createTime"])
        orderid = data["id"]
        order = OrderData(
            symbol=data["symbol"],
            exchange=Exchange.MEXC,
            orderid=orderid,
            type=OrderType.STOP,
            direction=DIRECTION_MEXC2VT[data["triggerSide"]],
            price=price,
            volume=float(data["vol"]),
            traded=traded,
            status=PLANSTATUS_MEXC2VT[data["state"]],
            datetime = order_datetime,
            gateway_name=self.gateway_name,
            offset=Offset.CLOSE
        )
        self.gateway.on_order(order)

        # 将成交数量四舍五入到正确精度
        trade_volume: float = float(data["vol"])
        contract: ContractData = symbol_contract_map.get(order.symbol, None)
        if contract:
            trade_volume = round_to(trade_volume, contract.min_volume)
        if order.traded == 0:
            return
        
        self.trade_count += 1

        trade = TradeData(
            symbol=order.symbol,
            exchange=Exchange.MEXC,
            orderid=order.orderid,
            tradeid=str(self.trade_count),
            direction=order.direction,
            offset=order.offset,
            price=float(data["triggerPrice"]),
            volume=float(data["vol"]),
            datetime= get_local_datetime(int(data["updateTime"])),
            gateway_name=self.gateway_name,
        )
        self.gateway.on_trade(trade)
    #------------------------------------------------------------------------------------------------- 
    def on_position(self,data:dict):
        """
        收到持仓回报
        """
        pos_data=data["data"]
        position = PositionData(
            symbol = pos_data["symbol"],
            exchange = Exchange.MEXC,
            direction = HOLDSIDE_MEXC2VT[pos_data["positionType"]],
            volume = float(pos_data["holdVol"]),
            price = float(pos_data["openAvgPrice"]),
            pnl = float(pos_data["realised"]),
            gateway_name = self.gateway_name
        )
        self.gateway.on_position(position)
#------------------------------------------------------------------------------------------------- 
def create_signature(secret:str,message:str):
    sign_str=hmac.new(bytes(secret, encoding="utf-8"),bytes(message, encoding="utf-8"), digestmod="sha256").hexdigest()
    return sign_str

def get_local_datetime(timestamp: float) -> datetime:
    """生成时间"""
    dt: datetime = datetime.fromtimestamp(timestamp / 1000)
    dt: datetime = dt.replace(tzinfo=CHINA_TZ)
    return dt
