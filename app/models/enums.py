from enum import Enum


class NotificationType(str, Enum):
    BID_OUTBID = "bid_outbid"
    BID_PLACED = "bid_placed"
    AUCTION_ENDING = "auction_ending"
    AUCTION_WON = "auction_won"
    AUCTION_LOST = "auction_lost"
    AUCTION_SOLD = "auction_sold"
    NEW_LOT = "new_lot"
