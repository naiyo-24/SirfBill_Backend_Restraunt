from .database import Base, engine, SessionLocal
from .user import User

# Retained shops and distributors for admin compatibility
from .shop import Shop
from .shop_settings import ShopSettings
from .distributor import Distributor

# Restaurant Domain Models (Clean Consolidated Schema)
from .restaurant_outlet import RestaurantOutlet
from .restaurant_menu import RestaurantMenuCategory, RestaurantMenuItem
from .restaurant_modifier import RestaurantModifierGroup
from .restaurant_table import RestaurantTable
from .restaurant_order import RestaurantOrder
from .restaurant_order_line import RestaurantOrderLine
from .restaurant_kitchen import RestaurantKitchenTicket, RestaurantKitchenTicketItem, RestaurantKitchenEvent
from .restaurant_tender import RestaurantTender, RestaurantRefund
from .restaurant_shift import RestaurantShift
from .restaurant_audit import RestaurantAuditEvent

# Inventory, Recipes & Procurement
from .restaurant_ingredient import RestaurantIngredient, RestaurantIngredientCategory
from .restaurant_procurement import (
    RestaurantSupplier,
    RestaurantPurchaseOrder,
    RestaurantPurchaseOrderItem,
    RestaurantGRN,
    RestaurantGRNItem
)
from .restaurant_recipe import RestaurantRecipe
from .restaurant_stock_ledger import RestaurantStockLedger
from .restaurant_stock_transfer import RestaurantStockTransfer, RestaurantStockTransferItem
from .restaurant_stock_audit import RestaurantStockAudit, RestaurantStockAuditItem

# CRM, Subscriptions & Hardware
from .restaurant_customer import RestaurantCustomer, RestaurantLoyaltyRules, RestaurantCustomerLedger
from .restaurant_subscription import SubscriptionPlan, TenantSubscription, SubscriptionPayment
from .hardware_product import HardwareProduct, HardwareOrder
from .service_plan import ServicePlan




