from mexc_order_placer import MexcOrderPlacer
placer=MexcOrderPlacer(rest_host="http://localhost:5102")


placer.place_stop_order('long',2000,0.01,2001,1999)
placer.place_limit_order('long',1600,0.01)
placer.place_stop_order('short',1600,0.01,1599,1601)
placer.place_limit_order('short',2000,0.01)



