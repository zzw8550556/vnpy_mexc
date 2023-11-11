from flask import Flask, request, jsonify
from mexc_browser_driver import MexcBrowserDriver,STR2DIRECTION

driver=MexcBrowserDriver(cfg_file_name='cfg.json')
driver.init_browser()

app = Flask(__name__)

@app.route('/place_limit_order', methods=['POST'])
def place_limit_order():
    data = request.json
    direction = STR2DIRECTION[data['direction']]
    price = float(data['price'])
    quantity = float(data['quantity'])
    
    result = driver.place_limit_order(direction, price, quantity)
    
    return jsonify(result)

@app.route('/place_stop_order', methods=['POST'])
def place_stop_order():
    data = request.json
    direction = STR2DIRECTION[data['direction']]
    trigger_price = float(data['trigger_price'])
    quantity = float(data['quantity'])
    take_profit_price = float(data['take_profit_price'])
    stop_loss_price = float(data['stop_loss_price'])
    
    result = driver.place_stop_order(direction, trigger_price, quantity, take_profit_price, stop_loss_price)
    
    return jsonify(result)

@app.route('/place_market_order', methods=['POST'])
def place_market_order():
    data = request.json
    direction = STR2DIRECTION[data['direction']]
    quantity = float(data['quantity'])
    
    result = driver.place_market_order(direction , quantity)
    
    return jsonify(result)

if __name__ == '__main__':
    app.run(port=5102)