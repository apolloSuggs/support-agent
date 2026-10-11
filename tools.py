"""Tool definitions for the support agent.

Every tool follows the tool-definitions skill: a clear, unique description
that says what the tool does, when to use it, when not to, and what it returns.
"""

send_verification_code = {
    "name": "send_verification_code",
    "description": (
        "Sends a one-time 6-digit verification code to the email address or phone number on a customer's account, "
        "to start proving who they are. "
        "Use this first, as soon as the customer gives an email or phone number and before anything that touches an account or order. "
        "Do not use this to check a code the customer typed — use verify_identity for that. "
        "Returns only a confirmation that a code was sent if an account exists. It never shows the code "
        "and does not say whether the account exists."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "The email address on the customer's account, e.g. 'jane@example.com'."
            },
            "phone": {
                "type": "string",
                "description": "The phone number on the customer's account, digits only with country code, e.g. '15551234567'. Use if no email is available."
            }
        },
        "required": []
    }
}

verify_identity = {
    "name": "verify_identity",
    "description": (
        "Confirms who a customer is by checking the 6-digit code they received against the email or phone number it was sent to. "
        "Use this after send_verification_code, once the customer tells you the code. "
        "Do not use this to send a code — use send_verification_code for that. Never guess or make up a code. "
        "Returns whether the customer is now verified. After 3 wrong codes it locks, and the customer must be handed to a human."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The 6-digit code the customer received, exactly as they typed it, e.g. '482913'."
            },
            "email": {
                "type": "string",
                "description": "The same email address the code was sent to, e.g. 'jane@example.com'."
            },
            "phone": {
                "type": "string",
                "description": "The same phone number the code was sent to, digits only with country code. Use if no email was given."
            }
        },
        "required": ["code"]
    }
}

lookup_customer = {
    "name": "lookup_customer",
    "description": (
        "Retrieves the verified customer's own account record using their email address or phone number. "
        "Use this only after verify_identity has succeeded, when you need their account ID, name, or recent order IDs. "
        "Do not use this to identify someone or to find out whether an account exists — use send_verification_code and verify_identity for that. "
        "Do not use this to check a specific order — use lookup_order_status for that. "
        "Returns the account ID, name, email, phone, and recent order IDs. "
        "It refuses if the customer is not verified or the email or phone belongs to a different account."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "The email address on the customer's account, e.g. 'jane@example.com'."
            },
            "phone": {
                "type": "string",
                "description": "The phone number on the customer's account, digits only with country code, e.g. '15551234567'. Use if no email is available."
            }
        },
        "required": []
    }
}

lookup_order_status = {
    "name": "lookup_order_status",
    "description": (
        "Looks up the current shipping and fulfillment status of a single existing order. "
        "Use when a customer asks where their order is or when it will arrive. "
        "Do not use this to change, cancel, or refund an order — use cancel_order or issue_refund for that. "
        "Requires a verified customer: use send_verification_code and verify_identity first, and only ask about orders on that customer's account. "
        "Returns the status, carrier, tracking number, and estimated delivery date."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The customer's order ID, e.g. 'ORD-10482'. Found in the confirmation email or from lookup_customer."
            }
        },
        "required": ["order_id"]
    }
}

cancel_order = {
    "name": "cancel_order",
    "description": (
        "Cancels an existing order that has not shipped yet, so the customer is never charged for it. "
        "Use only when the customer clearly asks to cancel an order that is still processing. "
        "Do not use this for orders that already shipped or were delivered — use issue_refund for those. "
        "Do not use this to check order status — use lookup_order_status for that. "
        "Requires a verified customer: use send_verification_code and verify_identity first, and only cancel orders on that customer's account. "
        "Returns whether the cancellation succeeded and, if not, why."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The ID of the order to cancel, e.g. 'ORD-10482'."
            },
            "reason": {
                "type": "string",
                "enum": ["changed_mind", "ordered_by_mistake", "too_slow", "other"],
                "description": "Why the customer is cancelling."
            }
        },
        "required": ["order_id"]
    }
}

issue_refund = {
    "name": "issue_refund",
    "description": (
        "Sends money back to the customer's original payment method for an order that was already charged. "
        "Use when a shipped or delivered order arrived damaged, wrong, or the customer is returning it. "
        "Do not use this for orders that have not shipped yet — use cancel_order instead. "
        "Requires a verified customer: use send_verification_code and verify_identity first, and only refund orders on that customer's account. "
        "Returns the refund ID, the amount refunded, and the date the customer should see it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The ID of the order being refunded, e.g. 'ORD-10482'."
            },
            "amount_cents": {
                "type": "integer",
                "description": "How much to refund, in cents, e.g. 2499 for $24.99. Leave out to refund the full order."
            },
            "reason": {
                "type": "string",
                "enum": ["damaged", "wrong_item", "not_received", "returned", "other"],
                "description": "Why the refund is being issued."
            }
        },
        "required": ["order_id", "reason"]
    }
}

search_orders = {
    "name": "search_orders",
    "description": (
        "Searches the verified customer's own orders by status or by a word from an item name, for when the customer does not know their order ID. "
        "Use when the customer describes an order ('my keyboard order') or asks which orders are still open. "
        "Do not use this when you already have an order ID — use lookup_order_status for that. "
        "Requires a verified customer. "
        "Returns up to 10 matching orders, each with its order ID, status, and item names."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["processing", "shipped", "delivered", "cancelled"],
                "description": "Only return orders with this status."
            },
            "keyword": {
                "type": "string",
                "description": "A word from an item name, e.g. 'keyboard'. Not case sensitive."
            }
        },
        "required": []
    }
}

update_shipping_address = {
    "name": "update_shipping_address",
    "description": (
        "Changes the delivery address on one order that has not shipped yet. "
        "Use only when the customer clearly asks to send an order somewhere else and the order is still processing. "
        "Do not use this to cancel an order — use cancel_order for that. "
        "Requires a verified customer who owns the order. "
        "Returns the new address, or why the change was not allowed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The ID of the order to change, e.g. 'ORD-10482'."
            },
            "street": {
                "type": "string",
                "description": "Street and number, e.g. '42 Oak Lane, Apt 5'."
            },
            "city": {
                "type": "string",
                "description": "City name, e.g. 'Austin'."
            },
            "state": {
                "type": "string",
                "description": "State or region, e.g. 'TX'."
            },
            "postal_code": {
                "type": "string",
                "description": "ZIP or postal code, e.g. '78701'."
            }
        },
        "required": ["order_id", "street", "city", "state", "postal_code"]
    }
}

apply_store_credit = {
    "name": "apply_store_credit",
    "description": (
        "Adds store credit to the customer's account instead of sending money back, for an order that was already charged. "
        "Use only when the customer chooses store credit over a cash refund. "
        "Do not use this to return money to the original payment method — use issue_refund for that. "
        "Requires a verified customer who owns the order. "
        "Returns the credit ID and the amount added."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The ID of the order the credit is for, e.g. 'ORD-10482'."
            },
            "amount_cents": {
                "type": "integer",
                "description": "How much credit to add, in cents, e.g. 2499 for $24.99. Leave out to credit the full order."
            },
            "reason": {
                "type": "string",
                "enum": ["damaged", "wrong_item", "not_received", "returned", "other"],
                "description": "Why the credit is being issued."
            }
        },
        "required": ["order_id", "reason"]
    }
}

search_help_articles = {
    "name": "search_help_articles",
    "description": (
        "Searches our help center for articles that answer general questions about policies, "
        "shipping times, returns, and how to use the product. "
        "Use when the customer's question is about how things work, not about their own account or order. "
        "Do not use this to look up a specific customer or order — use lookup_customer or lookup_order_status. "
        "Returns up to 5 matching articles with their title, a short summary, and a link."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A short plain-English search phrase, e.g. 'return policy for opened items'."
            }
        },
        "required": ["query"]
    }
}

create_support_ticket = {
    "name": "create_support_ticket",
    "description": (
        "Opens a support ticket so the support team can follow up on an issue later by email, "
        "or records a formal complaint (set ticket_type to 'complaint'). "
        "Use when the issue cannot be solved right now but is not urgent, such as a bug report, a "
        "request that needs a team member to review, or a customer who wants their complaint on record. "
        "Do not use this when the customer needs a live person right away — use escalate_to_human instead. "
        "Returns the ticket ID and the expected response date."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "The customer's account ID from lookup_customer, e.g. 'CUST-4492'."
            },
            "ticket_type": {
                "type": "string",
                "enum": ["problem", "complaint"],
                "description": "'problem' for something to be fixed (the default), 'complaint' for a formal complaint record."
            },
            "subject": {
                "type": "string",
                "description": "A one-line summary of the issue, e.g. 'Discount code not applying at checkout'."
            },
            "details": {
                "type": "string",
                "description": "A full description of the issue, what the customer said, and what you already tried."
            },
            "order_id": {
                "type": "string",
                "description": "The related order ID, if the issue is about a specific order, e.g. 'ORD-10482'."
            }
        },
        "required": ["customer_id", "subject", "details"]
    }
}

escalate_to_human = {
    "name": "escalate_to_human",
    "description": (
        "Hands the live conversation to a human support agent right now. "
        "Use when the customer asks for a person, is very upset, or the issue involves safety, legal, "
        "or billing disputes you cannot resolve. "
        "Do not use this for non-urgent issues that can wait for an email reply — use create_support_ticket instead. "
        "The system adds the verified customer, the actions taken so far and the agents involved, so you only supply the reason, summary and what the customer wants. Returns a handoff ID and the estimated wait."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "enum": ["customer_requested", "customer_upset", "billing_dispute", "safety_or_legal", "other"],
                "description": "Why the conversation is being handed off."
            },
            "summary": {
                "type": "string",
                "description": "A short summary of the conversation so the human agent does not need to ask again."
            },
            "customer_wants": {
                "type": "string",
                "description": "What outcome the customer is asking for, in one sentence, e.g. 'Cancel ORD-8821 and get money back'."
            },
            "suggested_next_step": {
                "type": "string",
                "description": "What you think the human should do first, e.g. 'Approve the $450 refund after checking the delivery photo'."
            }
        },
        "required": ["reason", "summary", "customer_wants"]
    }
}

transfer_to_agent = {
    "name": "transfer_to_agent",
    "description": (
        "Passes this conversation to a different support agent whose job fits what the customer needs now. "
        "Use when the request is outside your role (for example you cannot cancel orders or move money) "
        "or when the customer must be verified first and you have no verification tools. "
        "Do not use this for a live person — use escalate_to_human instead. "
        "Returns which agent took over. The customer's verification carries over, so they never verify twice."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["customer_service", "order_processing", "refund_processing"],
                "description": (
                    "Who to hand over to. customer_service: verification, account questions, help articles, tickets. "
                    "order_processing: order status, search, address change, cancellation. "
                    "refund_processing: refunds and store credit."
                )
            },
            "reason": {
                "type": "string",
                "description": "One sentence on why, so the next agent knows what the customer wants, e.g. 'Verified; wants to cancel ORD-8821'."
            }
        },
        "required": ["agent", "reason"]
    }
}

TOOLS = [
    send_verification_code,
    verify_identity,
    lookup_customer,
    lookup_order_status,
    search_orders,
    update_shipping_address,
    cancel_order,
    issue_refund,
    apply_store_credit,
    search_help_articles,
    create_support_ticket,
    escalate_to_human,
    transfer_to_agent,
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def tools_for(names):
    """The tool definitions for just these tool names. Each agent only sees its own."""
    return [TOOLS_BY_NAME[name] for name in names]
