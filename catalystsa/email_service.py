import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://catalystsa-frontend.vercel.app")


def send_email(to_address, subject, html_content):
    """
    Send email via Gmail SMTP
    Non-blocking - logs errors but doesn't crash
    """
    if not EMAIL_USER or not EMAIL_PASS:
        logger.warning("Email credentials not configured - skipping email")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = to_address

        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)

        logger.info(f"Email sent successfully to {to_address}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_address}: {str(e)}")
        return False


def send_customer_order_confirmation(order):
    """
    Send order confirmation email to customer
    """
    order_number = order.get("order_number", "N/A")
    customer_name = order.get("customer_name", "Customer")
    customer_email = order.get("customer_email")
    amount = order.get("amount", 0) / 100  # Convert cents to rands
    delivery_fee = order.get("delivery_fee", 0) / 100
    created_at = order.get("created_at", "")

    if not customer_email:
        logger.warning("No customer email provided - skipping customer confirmation")
        return False

    subject = f"Order Confirmed - #{order_number}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto;">
                <h1 style="color: #16a34a;">✓ Order Confirmed</h1>
                
                <p>Hi {customer_name},</p>
                
                <p>Thank you for your order! We've received your payment and are processing your order.</p>
                
                <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h2 style="margin-top: 0; color: #16a34a;">Order #<strong>{order_number}</strong></h2>
                    <p><strong>Order Date:</strong> {created_at}</p>
                    <p><strong>Total Amount:</strong> R{amount:.2f}</p>
                    <p><strong>Delivery Fee:</strong> R{delivery_fee:.2f}</p>
                </div>
                
                <h3>Track Your Order</h3>
                <p>
                    <a href="{FRONTEND_URL}/orders/{order_number}" 
                       style="background-color: #16a34a; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
                        View Order Details
                    </a>
                </p>
                
                <h3>Delivery Information</h3>
                <p>
                    <strong>Estimated Delivery:</strong> 3-7 business days<br>
                    <strong>Delivery Address:</strong><br>
                    {order.get('address', 'N/A')}<br>
                    {order.get('city', 'N/A')}, {order.get('postal_code', 'N/A')}
                </p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                
                <p style="font-size: 12px; color: #666;">
                    If you have any questions, please reply to this email or contact us at {EMAIL_USER}
                </p>
                
                <p style="font-size: 12px; color: #666;">
                    <strong>Catalyst SA Store</strong>
                </p>
            </div>
        </body>
    </html>
    """

    return send_email(customer_email, subject, html_content)


def send_admin_order_notification(order):
    """
    Send order notification email to admin
    """
    if not ADMIN_EMAIL:
        logger.warning("Admin email not configured - skipping admin notification")
        return False

    order_number = order.get("order_number", "N/A")
    customer_name = order.get("customer_name", "Unknown")
    customer_email = order.get("customer_email", "N/A")
    phone = order.get("phone", "N/A")
    address = order.get("address", "N/A")
    city = order.get("city", "N/A")
    postal_code = order.get("postal_code", "N/A")
    amount = order.get("amount", 0) / 100
    delivery_fee = order.get("delivery_fee", 0) / 100
    total = amount + delivery_fee
    items = order.get("items", "[]")

    subject = f"🚀 NEW ORDER #{order_number} - R{total:.2f}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto;">
                <h1 style="color: #dc2626;">🚀 NEW ORDER RECEIVED</h1>
                
                <div style="background-color: #fef2f2; padding: 20px; border-radius: 8px; border-left: 4px solid #dc2626; margin: 20px 0;">
                    <h2 style="margin-top: 0; color: #dc2626;">Order #{order_number}</h2>
                    <p><strong>Status:</strong> PAID - Ready to Process</p>
                </div>
                
                <h3 style="border-bottom: 2px solid #16a34a; padding-bottom: 10px;">📦 CUSTOMER DETAILS</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px; font-weight: bold; width: 150px;">Name:</td>
                        <td style="padding: 8px;">{customer_name}</td>
                    </tr>
                    <tr style="background-color: #f9fafb;">
                        <td style="padding: 8px; font-weight: bold;">Email:</td>
                        <td style="padding: 8px;">{customer_email}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Phone:</td>
                        <td style="padding: 8px;">{phone}</td>
                    </tr>
                </table>
                
                <h3 style="border-bottom: 2px solid #16a34a; padding-bottom: 10px; margin-top: 20px;">📍 DELIVERY ADDRESS</h3>
                <p style="margin: 10px 0;">
                    {address}<br>
                    {city}, {postal_code}<br>
                    South Africa
                </p>
                
                <h3 style="border-bottom: 2px solid #16a34a; padding-bottom: 10px; margin-top: 20px;">💰 ORDER SUMMARY</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Subtotal:</td>
                        <td style="padding: 8px; text-align: right;">R{amount:.2f}</td>
                    </tr>
                    <tr style="background-color: #f9fafb;">
                        <td style="padding: 8px; font-weight: bold;">Delivery:</td>
                        <td style="padding: 8px; text-align: right;">R{delivery_fee:.2f}</td>
                    </tr>
                    <tr style="border-top: 2px solid #ddd; background-color: #f0fdf4;">
                        <td style="padding: 8px; font-weight: bold; font-size: 16px;">TOTAL PAID:</td>
                        <td style="padding: 8px; text-align: right; font-weight: bold; font-size: 16px; color: #16a34a;">R{total:.2f}</td>
                    </tr>
                </table>
                
                <h3 style="border-bottom: 2px solid #16a34a; padding-bottom: 10px; margin-top: 20px;">📋 ITEMS</h3>
                <p style="background-color: #f9fafb; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    {items}
                </p>
                
                <div style="background-color: #fef08a; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-weight: bold;">⚠️ ACTION REQUIRED:</p>
                    <p style="margin: 5px 0 0 0;">Process payment and prepare for fulfillment</p>
                </div>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                
                <p style="font-size: 12px; color: #666;">
                    Order timestamp: {order.get('created_at', '')}<br>
                    This is an automated notification from Catalyst SA Store
                </p>
            </div>
        </body>
    </html>
    """

    return send_email(ADMIN_EMAIL, subject, html_content)
