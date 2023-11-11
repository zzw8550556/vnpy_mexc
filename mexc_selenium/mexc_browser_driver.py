from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import json,time
from enum import Enum


class Direction(Enum):
    """
    Direction of order/trade/position.
    """
    LONG = "long"
    SHORT = "short"
class OrderType(Enum):
    """
    Direction of order/trade/position.
    """
    STOP = "stop"
    LIMIT = "limit"
    MARKET = "market"
STR2DIRECTION = {
    "long" : Direction.LONG,
    "short" : Direction.SHORT
}

class MexcBrowserDriver:
    def __init__(self,cfg_file_name:str):
        # 初始化函数，可以在这里进行一些初始化操作
        self.driver : webdriver.Chrome
        self.限价按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[1]/div/span[1]'
        self.限价价格输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[1]/div/div[2]/div/div/input'
        self.限价数量输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[2]/div/div[2]/div/div/input'
        self.计划委托按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[1]/div/span[3]/button'
        self.触发价格输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[1]/div/div[2]/div/div/input'
        self.价格输入区域 = r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[2]'
        self.市价按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[2]/div/div[2]/div/div/span'
        self.数量输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[3]/div/div[2]/div/div/input'
        self.做多止盈止损按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[11]/div/div[1]'
        self.做空止盈止损按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[11]/div/div[2]'
        self.止盈输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[11]/section/div[2]/div[1]/div/div/div/div/div/input'
        self.止损输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[11]/section/div[5]/div[1]/div/div/div/div/div/input'
        self.开多按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/section/div[1]/div[1]/button'
        self.开空按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/section/div[2]/div[1]/button'
        self.风险提示框=r'//*[contains(text(), "风险提示")]'
        self.风险提示确定按钮=r'//*[contains(text(), "确 定")]'
        self.确定买入做多=r'//*[contains(text(), "确定买入/做多")]'
        self.确定卖出做空=r'//*[contains(text(), "确定卖出/做空")]'
        self.限价单确定按钮=r'//*[contains(text(), "确 定")]'
        self.市价单按钮=r'//*[@id="mexc_contract_v_open_way_position"]/div[1]/div/span[2]'
        self.市价数量输入框=r'//*[@id="mexc_contract_v_open_way_position"]/div[4]/div[1]/div/div[2]/div/div/input'

        with open(cfg_file_name,"r") as fp:
            self.cfg=json.load(fp)

    def init_browser(self):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(f'--user-data-dir={self.cfg["user-data-dir"]}')
        chrome_options.set_capability("goog:loggingPrefs", {'performance': 'ALL'})
        # 初始化webdriver
        self.driver = webdriver.Chrome(options=chrome_options,service=Service(ChromeDriverManager().install()))
        # 调整浏览器窗口大小
        self.driver.set_window_size(800, 800)
        # 访问网站
        self.driver.get('https://futures.mexc.com/exchange/ETH_USDT?type=linear_swap')
        # 等待检测到计划委托按钮出现
        wait = WebDriverWait(self.driver, 30)  # 等待最长30秒
        try:
            wait.until(EC.visibility_of_element_located((By.XPATH, self.计划委托按钮)))
        except TimeoutError as e:
            print('没检测到计划委托按钮')
    def place_limit_order(self, direction:Direction , price:float, quantity:float ):
        # 下限价单函数
        # 参数：下单价格（price），下单数量（quantity），下单方向（direction）
        # 在这里实现下限价单的逻辑
        button_element = self.driver.find_element(By.XPATH, self.限价按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        input_element = self.driver.find_element(By.XPATH, self.限价价格输入框)
        self.clear_input_content(input_element)
        input_element.send_keys(f'{price}')


        input_element = self.driver.find_element(By.XPATH, self.限价数量输入框)
        self.clear_input_content(input_element)
        input_element.send_keys(f'{quantity}')

        if direction==Direction.LONG:
            button_element = self.driver.find_element(By.XPATH, self.开多按钮)
        else:
            button_element = self.driver.find_element(By.XPATH, self.开空按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        dlg_title=None
        try:
            if direction==Direction.LONG:
                is_present = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, self.确定买入做多)))
                dlg_title = self.driver.find_element(By.XPATH, self.确定买入做多)
            else:
                is_present = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, self.确定卖出做空)))
                dlg_title = self.driver.find_element(By.XPATH, self.确定卖出做空)
        except Exception:
            is_present = None
        if is_present and dlg_title:
            self.driver.get_log("performance")
            button_element=dlg_title.find_element(By.XPATH, "../../div[3]/div[1]/div[1]/button[2]")
            ActionChains(self.driver).click(button_element).perform()

        msg=self.get_response(OrderType.LIMIT)
        return msg

    def place_stop_order(self, direction:Direction, trigger_price:float, quantity:float, take_profit_price:float, stop_loss_price:float):
        # 下计划委托函数
        # 参数：触发价格（trigger_price），止盈价格（take_profit_price），止损价格（stop_loss_price），下单方向（direction）
        # 在这里实现下计划委托的逻辑
        # 填写特定xpath的输入框
        button_element = self.driver.find_element(By.XPATH, self.计划委托按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        input_element = self.driver.find_element(By.XPATH, self.触发价格输入框)
        self.clear_input_content(input_element)
        input_element.send_keys(f'{trigger_price}')

        element = self.driver.find_element(By.XPATH, self.价格输入区域)
        # 检查元素的class属性
        class_name = element.get_attribute('class')
        # 如果class的值是"pages-contract-handle-component-index-marketInputV"，则点击另一个元素
        if class_name == 'pages-contract-handle-component-index-numberInput':
            button_element = self.driver.find_element(By.XPATH, self.市价按钮)
            ActionChains(self.driver).click(button_element).perform()

        input_element = self.driver.find_element(By.XPATH, self.数量输入框)
        self.clear_input_content(input_element)
        input_element.send_keys(f'{quantity}')

        if direction==Direction.LONG:
            button_element = self.driver.find_element(By.XPATH, self.做多止盈止损按钮)
        else:
            button_element = self.driver.find_element(By.XPATH, self.做空止盈止损按钮)
        class_name = button_element.get_attribute('class')
        if class_name == 'components-checkbox-index-wrapper check-box-wrapper':
            self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
            ActionChains(self.driver).click(button_element).perform()

        input_element = self.driver.find_element(By.XPATH, self.止盈输入框)
        self.clear_input_content(input_element)
        if take_profit_price!=-1:
            input_element.send_keys(f'{take_profit_price}')

        input_element = self.driver.find_element(By.XPATH, self.止损输入框)
        self.clear_input_content(input_element)
        if stop_loss_price!=-1:
            input_element.send_keys(f'{stop_loss_price}')

        if direction==Direction.LONG:
            button_element = self.driver.find_element(By.XPATH, self.开多按钮)
        else:
            button_element = self.driver.find_element(By.XPATH, self.开空按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        dlg_titles=None

        time.sleep(0.5)
        #is_present = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, self.风险提示框)))
        dlg_titles = self.driver.find_elements(By.XPATH, self.风险提示框)
        if dlg_titles:
            self.driver.get_log("performance")
            for dlg_title in dlg_titles:
                if dlg_title.is_displayed() == True:
                    button_element=dlg_title.find_element(By.XPATH, "../../div[3]/div[1]/button[2]")
                    time.sleep(0.5)
                    ActionChains(self.driver).click(button_element).perform()

        msg=self.get_response(OrderType.STOP)
        return msg
    
    def place_market_order(self, direction:Direction , quantity:float ):
        # 下市价单函数
        # 参数：下单数量（quantity），下单方向（direction）
        # 在这里实现下市价单的逻辑
        button_element = self.driver.find_element(By.XPATH, self.市价单按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        input_element = self.driver.find_element(By.XPATH, self.市价数量输入框)
        self.clear_input_content(input_element)
        input_element.send_keys(f'{quantity}')

        if direction==Direction.LONG:
            button_element = self.driver.find_element(By.XPATH, self.开多按钮)
        else:
            button_element = self.driver.find_element(By.XPATH, self.开空按钮)
        self.driver.execute_script("arguments[0].scrollIntoView();", button_element)
        ActionChains(self.driver).click(button_element).perform()

        dlg_title=None
        try:
            if direction==Direction.LONG:
                is_present = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, self.确定买入做多)))
                dlg_title = self.driver.find_element(By.XPATH, self.确定买入做多)
            else:
                is_present = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, self.确定卖出做空)))
                dlg_title = self.driver.find_element(By.XPATH, self.确定卖出做空)
        except Exception:
            is_present = None
        if is_present and dlg_title:
            self.driver.get_log("performance")
            button_element=dlg_title.find_element(By.XPATH, "../../div[3]/div[1]/div[1]/button[2]")
            ActionChains(self.driver).click(button_element).perform()

        msg=self.get_response(OrderType.MARKET)
        return msg
    
    def clear_input_content(self,input_element):
        # 使用Ctrl+A全选输入框的内容
        input_element.send_keys(Keys.CONTROL, 'a')
        # 使用Delete键删除选中的内容
        input_element.send_keys(Keys.DELETE)

    def get_response(self,order_type:OrderType):
        time.sleep(3)
        logs = self.driver.get_log("performance")
        for item in logs:
            log = json.loads(item["message"])["message"]
            if log["method"] == 'Network.responseReceived':
                url = log['params']['response']['url']
                if url == 'data:,':  # 过滤掉初始data页面，后续可以根据 log['params']['response']['type']过滤请求类型
                    continue
                #response_time = log['params']['response']['responseTime']
                if order_type==OrderType.LIMIT:
                    urlpfx='https://futures.mexc.com/api/v1/private/order/create'
                    #{"success":true,"code":0,"data":{"orderId":"477474613211788800","ts":1699509218841}}
                elif order_type==OrderType.MARKET:
                    urlpfx='https://futures.mexc.com/api/v1/private/order/create'
                else:
                    urlpfx='https://futures.mexc.com/api/v1/private/planorder/place/v2'
                    #{"success":true,"code":0,"data":"477474127838541312"}
                if urlpfx in url:
                    print('请求', url)
                    request_id = log['params']['requestId']
                    response_body = self.driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})['body']
                    return response_body