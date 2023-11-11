import requests

class MexcOrderPlacer:
    def __init__(self,rest_host:str):
        self.rest_host = rest_host

    def place_limit_order(self,direction, price, quantity):
        data = {
            'direction': direction,
            'price': price,
            'quantity': quantity
        }
        response = requests.post(f'{self.rest_host}/place_limit_order', json=data)
        print(response.json())

    def place_stop_order(self,direction, trigger_price, quantity, take_profit_price, stop_loss_price):
        data = {
            'direction': direction,
            'trigger_price': trigger_price,
            'quantity': quantity,
            'take_profit_price': take_profit_price,
            'stop_loss_price': stop_loss_price
        }
        response = requests.post(f'{self.rest_host}/place_stop_order', json=data)
        print(response.json())

    def place_market_order(self,direction , quantity):
        data = {
            'direction': direction,
            'quantity': quantity
        }
        response = requests.post(f'{self.rest_host}/place_market_order', json=data)
        print(response.json())


