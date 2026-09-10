# Per-campaign content and config, sourced from Linkedin Lead Gen Revised.docx
# (original + the updated '(1)' copy - GCC calendar links and the Email Marketing
# sequence came from the updated copy).
#
# ARCHITECTURE: campaign is the primary unit. The Google Sheet ONLY tags each lead
# with a 'Campaigns' value (e.g. 'SCM Podcast') - it never says which physical
# LinkedIn account handles that lead. That assignment lives entirely here in code,
# because one campaign's content can be run by SEVERAL different accounts at once.
#
#   - 'search_url' : the Sales Navigator search URL used to source leads for THIS
#                     campaign. Used by the first account in 'accounts' to run the
#                     actual search (any logged-in session can run it - the search
#                     result doesn't depend on which account performs it).
#                     OPTIONAL per-account 'search_url' inside an 'accounts' entry:
#                     lets ONE campaign source leads from several different saved
#                     searches (e.g. GCC runs a different search per associate).
#                     salesApiLeadSearch.py runs the campaign-level search with the
#                     first account, then runs every per-account search_url with its
#                     own account's session. All leads still get tagged with the
#                     campaign's single 'Campaigns' value.
#   - 'accounts'   : an ORDERED list of {account, invite_limit, inmail_limit,
#                     message_limit, calendar_url}. Each 'account' must be a key in
#                     get_cookies.ACCOUNTS. Every account here gets its OWN
#                     independent daily budget and its OWN
#                     daily_run_counts_<campaign>_<account>.json file - SCM Podcast
#                     via Ranganathan and SCM Podcast via Andrew never share a
#                     counter. 'calendar_url' is optional - only needed if the
#                     campaign's message text uses the {calendar_url} placeholder
#                     (see SCM Podcast below); accounts sharing one campaign but
#                     needing different booking links is exactly what this is for.
#                     IMPORTANT: campaign_id (this dict's top-level key) is a
#                     literal value filtered against the sheet's 'Campaigns' column
#                     - never rename an existing key, or every lead already tagged
#                     with the old name stops matching anything. If two accounts on
#                     one campaign need different content, differentiate via
#                     per-account fields (like calendar_url) INSIDE that campaign's
#                     'accounts' list, not by splitting into two dict keys.
#
#     HOW LEADS SPLIT ACROSS MULTIPLE ACCOUNTS ON ONE CAMPAIGN:
#     salesApiConnection.py fills this list in ORDER - the first account sends to
#     campaign leads until IT hits its own invite_limit/inmail_limit for the day,
#     then whatever's left over rolls to the next account in the list, and so on.
#     The moment a lead is actually contacted, its row moves to the 'Followup msg'
#     sheet carrying BOTH 'Campaigns' and 'Associate Account' (the specific login
#     that sent it) - that sheet is the only record of which account owns which
#     lead. salesApiMessagingThreadsCheckingReplies.py and
#     salesApiMessagingThreadsSendMessages.py filter on those two columns to know
#     which login to keep using for a given lead. No local file involved.
#
# Current mapping (associate users per the revised campaign doc):
#   SCM Podcast             -> Ranganathan A, Andrew Dreger
#   Distriops               -> Nandhini A
#   Sales Outsourcing       -> Cynthia David
#   Procurement             -> Andrew Dreger
#   GCC                     -> Cynthia David, Ranganathan A (each runs their own saved search)
#   CXO - Operating Partner -> Andrew Dreger, Cynthia David
#
# 'invite_track' index meaning (invite/connection path):
#   [0] = sent right after they accept the connection (salesApiMessagingThreadsCheckingReplies.py)
#   [1] = 1st dated follow-up, +3 days   (salesApiMessagingThreadsSendMessages.py)
#   [2] = 2nd dated follow-up, +5 days   (salesApiMessagingThreadsSendMessages.py)
#   [3] = 3rd dated follow-up, +7 days   (salesApiMessagingThreadsSendMessages.py)
# Shorter lists just stop the sequence early - campaigns with only 2 entries never
# send a stage-2/3 follow-up because there's no template to send.
#
# 'inmail_track' index meaning (direct InMail path, only used if the campaign has one):
#   [0] = 1st InMail follow-up, +3 days
#   [1] = 2nd InMail follow-up, +5 days
#   [2] = 3rd InMail follow-up, +7 days
# Empty list = no InMail follow-up sequence, just the single initial InMail.
# Each entry is a dict {'subject': ... or None, 'body': ...} - unlike invite_track (no
# subject on connection/invite messages), InMail follow-ups can each carry their own subject.
#
# 'email_track' (OPTIONAL, content-only): the Email Marketing sequence for a
# campaign, same {'subject', 'body'} shape as 'inmail_track' (initial + follow-ups).
# No script consumes it yet - it's the email-channel copy, kept in the registry so
# a future email-outreach module can read it. See GCC for an example.
#
# All message text may use {first_name} and, where relevant, {calendar_url} - both
# are filled in at send time from the record being messaged and the specific
# account's 'calendar_url' (see 'accounts' above).

DEFAULT_SEARCH_URL = 'https://www.linkedin.com/sales/search/people?query=(spellCorrectionEnabled%3Atrue%2CrecentSearchParam%3A(doLogHistory%3Atrue)%2Cfilters%3AList((type%3ACOMPANY_HEADQUARTERS%2Cvalues%3AList((id%3A103644278%2Ctext%3AUnited%2520States%2CselectionType%3AINCLUDED))))%2Ckeywords%3Asupply%2520chain)'

# Default daily budgets applied when a campaign doesn't override them.
DEFAULT_INVITE_LIMIT = 10
DEFAULT_INMAIL_LIMIT = 10
DEFAULT_MESSAGE_LIMIT = 30

CAMPAIGNS = {
    'SCM Podcast': {
        'search_url': DEFAULT_SEARCH_URL,
        'accounts': [
            {'account': 'Ranganathan A', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT, 'calendar_url': 'https://calendly.com/vserve/discovery-call-with-cynthia-vserve'},
            # {'account': 'Andrew Dreger', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT, 'calendar_url': 'https://calendar.google.com/calendar/u/0/appointments/schedules/AcZssZ3cYfeKA8Bg0bNkDXZbOgcmAoe372pduMfk7hWIxT_rS1CTjyd7IuEPMv5zMa8n6YsU-vGPmJY1'},
        ],
        'invite': "Hi {first_name}, we bring supply chain leaders onto our SCM Podcast and amplify their insights across channels to position them as experts. Our YouTube clips are crossing 1K+ views, you would be a strong fit which could support your visibility in the space. Open to connect?",
        'invite_track': [
            "Hi {first_name}, your perspective on supply chain strategy stood out. This is a paid podcast opportunity where we compensate our guests.\n\nWe feature leaders on our podcast and turn their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost.\n\nYou would get access to our 25K plus LinkedIn audience, along with short clips and posts you can reuse, and some of our YouTube clips are already crossing 1K plus views.\n\nIf this looks relevant, you can book here: {calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos",
            "Hi {first_name},\n\nJust wanted to follow up in case this got missed.\n\nWe're featuring supply chain leaders on our podcast and turning their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost. We also compensate our guests for participating.\n\nWe create short clips, posts, and other assets you can reuse, and some of our YouTube clips are already crossing 1K plus views.\n\nIf this looks relevant, you can book here: {calendar_url}\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos",
            "Hi {first_name},\n\nWe're locking the final few slots for this month's Supply Chain Leaders podcast, so this will be my last note.\n\nWe feature leaders and turn their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost.\n\nIn fact, we pay our guests for participating.\n\nIf you would like to be included, you can secure a slot here: {calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos",
            "Hi {first_name}, just wanted to do a quick follow-up regarding the Supply Chain Leaders Podcast.\n\nWe'd still love to feature your perspective and turn the conversation into multi-channel content across LinkedIn and YouTube to help strengthen your visibility in the space. We also compensate our guests for participating.\n\nA few of our recent clips have crossed 1K+ views, and I believe your insights would resonate well with the audience.\n\nIf you're open to joining, you can grab a slot here:\n{calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos",
        ],
        'inmail_subject': "We'd Like to Feature Your Supply Chain Insights",
        'inmail': "Hi {first_name}, your perspective on supply chain strategy stood out. This is a paid podcast opportunity where we compensate our guests.\n\nWe feature leaders on our podcast and turn their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost.\n\nYou would get access to our 25K plus LinkedIn audience, along with short clips and posts you can reuse, and some of our YouTube clips are already crossing 1K plus views.\n\nIf this looks relevant, you can book here: {calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos",
        'inmail_track': [
            {'subject': 'Get Featured on Our Supply Chain Podcast', 'body': "Hi {first_name},\n\nJust wanted to follow up in case this got missed.\n\nWe're featuring supply chain leaders on our podcast and turning their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost. We also compensate our guests for participating.\n\nWe create short clips, posts, and other assets you can reuse, and some of our YouTube clips are already crossing 1K plus views.\n\nIf this looks relevant, you can book here: {calendar_url}\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos"},
            {'subject': "We'd Like to Feature Your Supply Chain Insights", 'body': "Hi {first_name},\n\nWe're locking the final few slots for this month's Supply Chain Leaders podcast, so this will be my last note.\n\nWe feature leaders and turn their insights into multi channel content to position them as experts across LinkedIn and YouTube at zero cost.\n\nIn fact, we pay our guests for participating.\n\nIf you would like to be included, you can secure a slot here: {calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos"},
            {'subject': "We'd Like to Feature Your Supply Chain Insights", 'body': "Hi {first_name}, just wanted to do a quick follow-up regarding the Supply Chain Leaders Podcast.\n\nWe'd still love to feature your perspective and turn the conversation into multi-channel content across LinkedIn and YouTube to help strengthen your visibility in the space. We also compensate our guests for participating.\n\nA few of our recent clips have crossed 1K+ views, and I believe your insights would resonate well with the audience.\n\nIf you're open to joining, you can grab a slot here:\n{calendar_url}\n\nPast episodes:\nhttps://www.youtube.com/@VserveEbusinessSolutions/videos"},
        ],
    },
    'Distriops': {
        'search_url': DEFAULT_SEARCH_URL,
        'accounts': [
            {'account': 'Nandhini A', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
        ],
        'invite': "Hi {first_name}, we recently sent you an email about a partnership with DistriOps. As a DistriOps partner, we can help generate qualified leads for your company through our vendor network. Please review the email and share your thoughts. Happy to schedule a quick call to discuss.",
        'invite_track': [
            "Thanks for connecting, {first_name}.\n\nDistriops is a B2B partner network that connects businesses with trusted service providers. We've already registered your company in our vendor database because we believe your services would be valuable to businesses in our network.\n\nAs a Distri Ops partner, we can connect your company with organizations looking for the services you provide, helping generate qualified leads and new business opportunities.\n\nYou can learn more about Distriops here: https://distriops.com/\n\nI'd be happy to schedule a quick 15-minute call to explain how the partnership works and answer any questions you may have.",
            "Hi {first_name}, just following up on my previous message regarding the Distriops partnership.\n\nWe'd be glad to have your company as part of our partner network and explore opportunities to connect you with relevant businesses looking for your services.\n\nWould you be open to a quick 15-minute call this week to discuss how it works?",
            "Hi {first_name}, just wanted to follow up one last time regarding the DistriOps partnership.\n\nWe'd be happy to have you as part of our partner network and explore potential opportunities to connect you with relevant businesses looking for your services.\n\nWould you be open to a quick 15-minute call to discuss?",
        ],
        'inmail_subject': 'Grow Your Business with the Distri Ops Partner Network',
        'inmail': "Hi {first_name},\n\nWe recently sent you an email regarding a partnership opportunity with Distrops and wanted to follow up here as well.\n\nWe're building a network of trusted partners and believe your company would be a great fit. As a partner, we'll connect your business with organizations looking for the services you provide, helping generate qualified leads.\n\nWhen you have a chance, I'd appreciate it if you could review the email and share your thoughts. If it's easier, I'd be happy to schedule a quick 15-minute call to discuss the opportunity.\n\nLooking forward to hearing from you!",
        'inmail_track': [
            {'subject': 'Following Up on the DistriOps Partnership', 'body': "Hi {first_name},\n\nJust following up on my previous email regarding the DistriOps partner network.\n\nWe'd be glad to have you join our network and explore opportunities to connect your services with businesses looking for trusted providers.\n\nYou can learn more about Distriops here: https://distriops.com/\n\nWould you be available for a quick 15-minute call to discuss how the partnership works?\n\nLooking forward to hearing from you."},
            {'subject': 'DistriOps Partnership Opportunity', 'body': "Hi {first_name},\n\nI wanted to check in regarding the DistriOps partnership opportunity I shared earlier.\n\nOur partner network is designed to help businesses connect with relevant organizations and generate new business opportunities.\n\nWould you be open to a brief call this week to learn more?"},
            {'subject': 'Final Follow-Up – DistriOps Partnership', 'body': "Hi {first_name},\n\nJust reaching out one last time regarding the DistriOps partnership opportunity.\n\nWe'd be happy to explore whether this could be a good fit for your business. If you're interested, I'm happy to arrange a quick 15-minute call at a time that works for you.\n\nPlease let me know your thoughts."},
        ],
    },
    # 'Sales Outsourcing': {
    #     'search_url': DEFAULT_SEARCH_URL,
    #     'accounts': [
    #         {'account': 'Cynthia David', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #     ],
    #     'invite': "Hi {first_name}, I work with distributors, helping them create more sales opportunities without adding workload to their existing sales teams. We support businesses in building stronger outbound pipelines and connecting with potential customers. Would love to connect on a call to explore more.",
    #     'invite_track': [
    #         "{first_name}, Thanks for connecting. Quick question, are you currently using an SDR team for outbound, or is most pipeline generation coming from marketing/referrals?.\nDo you have 15 minutes this week for a quick call? Feel free to grab a time here: https://calendly.com/vserve/lin-call-with-vserve or share your next email id to share more information",
    #         "{first_name}, Just circling back one last time. If improving meeting flow and freeing up your team is a priority, this could be relevant. Happy to walk you through how it works in 15 mins. You can pick a time here: https://calendly.com/vserve/lin-call-with-vserve or share your email.",
    #     ],
    #     'inmail_subject': 'Outbound Sales Support for Industrial Distributors',
    #     'inmail': "Hi {first_name},\n\n{{First Name}}, Just circling back one last time. If improving meeting flow and freeing up your team is a priority, this could be relevant. Happy to walk you through how it works in 15 mins. You can pick a time here: https://calendly.com/vserve/lin-call-with-vserve or share your email.",
    #     'inmail_track': [
    #         {'subject': 'Lower-Cost Outbound Sales Support', 'body': "Hi {first_name}, just checking back. If you're:\n• Looking to reduce operational costs\n• Looking to improve operational efficiency\n• Considering outsourcing to scale operations\nVserve could be a great fit. We help businesses reduce costs by up to 50% while improving efficiency with skilled, flexible teams. Open to a quick call?"},
    #         {'subject': 'Lower-Cost Outbound Sales Support', 'body': "One challenge we often see is that sales teams have opportunities to pursue, but limited time for consistent prospecting and follow-ups can slow pipeline growth.\n\nWith Vserve's outbound sales support starting at $7/hour, your team can extend its prospecting capacity without the cost of adding more full-time resources.\n\nWould it be worth a quick 15-minute conversation to see if this could fit your growth plans?\n\nYou can pick a convenient time here: https://calendly.com/vserve/lin-call-with-vserve"},
    #         {'subject': 'Lower-Cost Outbound Sales Support', 'body': "Just making one final follow-up before I close the loop.\n\nIf expanding your outbound sales efforts without adding significant full-time costs is a priority, Vserve may be worth exploring. We can support prospecting, lead generation, and follow-ups with trained teams from India and the Philippines.\n\nWould you be open to a quick 15-minute conversation?\n\nYou can choose a time here: https://calendly.com/vserve/lin-call-with-vserve\n\nOr, if easier, share your best email address and I'll send a brief overview."},
    #     ],
    # },
    'Procurement': {
        'search_url': DEFAULT_SEARCH_URL,
        'accounts': [
            {'account': 'Andrew Dreger', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
        ],
        'invite': "Hi {first_name}, Procurement teams should focus on cost savings, not supplier follow-ups, PO management, and inventory issues. We help companies reduce costs by 40-50% through Procurement, Supplier Management, PO Operations, AP, and Inventory support. Would love to connect on a call and explore further.",
        'invite_track': [
            "{first_name}, We currently provide ongoing support to companies such as Building Controls & Solutions, TestEquity, DTS, Relevant, and HighGround, helping reduce operating costs by up to 50%. I'd love to share how we can support your team in a cost-effective way. Are you available for a quick call this week? You can pick a convenient time here: https://calendly.com/vserve/lin-call-with-vserve",
            "{first_name}, If this week is busy, no problem. Feel free to book a time for next week, and I'd be happy to walk you through how we help companies reduce operating costs by up to 50% with dedicated offshore support.",
        ],
        'inmail_subject': 'How Procurement Teams Are Reducing Costs',
        'inmail': "Hey {first_name}, I wanted to reach out because many procurement and supply chain teams are under pressure to do more with the same resources while managing supplier communication, purchase orders, inventory updates, AP support, and logistics coordination.\n\nAt Vserve, we provide dedicated procurement support teams from India and the Philippines that act as an extension of your operations. We help businesses streamline procurement, supplier management, PO processing, inventory management, accounts payable support, and logistics operations typically reducing operational costs by 60-70% while improving efficiency.\n\nI'm curious, are your procurement operations managed in-house or with outsourced support? If you're looking to improve efficiency and reduce costs, I'd be happy to share how we've helped similar organizations.\n\nWould you be open to a quick conversation to walk you through how it works in 15 mins. You can pick a time here: https://calendly.com/vserve/lin-call-with-vserve, or could you share the best email address to send more information?",
        'inmail_track': [
            {'subject': 'Reducing Procurement Workload & Costs', 'body': "Hi {first_name}, just checking back. If you're:\n• Looking to reduce operational costs\n• Looking to improve operational efficiency\n• Considering outsourcing to scale operations\nVserve could be a great fit. We help businesses reduce costs by up to 50% while improving efficiency with skilled, flexible teams. Open to a quick call?"},
            {'subject': 'Reducing Procurement Workload & Costs', 'body': "One common challenge we hear from procurement teams is that supplier follow-ups, PO processing, inventory updates, and AP tasks take up valuable time that could be spent on strategic priorities.\n\nVserve helps take these operational tasks off your team's plate with dedicated support teams, helping reduce costs and improve efficiency.\n\nWould you be open to a quick 15-minute conversation? You can pick a convenient time here: https://calendly.com/vserve/lin-call-with-vserve"},
            {'subject': 'Reducing Procurement Workload & Costs', 'body': "{first_name},\n\nI wanted to make one final follow-up. If procurement tasks like supplier follow-ups, PO processing, inventory updates, and AP support are taking up your team's time, Vserve may be able to help reduce the workload and operating costs.\n\nIf this is something you're exploring, could you share the best email address? I'd be happy to send a brief overview of how we can support your team."},
        ],
    },
    'GCC-Cynthia': {
        'accounts': [
            {'account': 'Cynthia David', 'search_url': 'https://www.linkedin.com/sales/search/people?savedSearchId=1993778340', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
        ],
        'invite': "Hi {first_name}, we’re featuring GCC leaders and transformation experts on the Industrial Distributors Podcast. Given your experience scaling GCC operations, we’d love to hear your insights on digital transformation, operational excellence, and the future of global teams. Open to a quick conversation?",
        'invite_track': [
            "Hi {first_name}, just following up on my earlier message. We’re bringing together GCC executives to discuss real-world experiences around scaling teams, process transformation, and building global capabilities. Your perspective would be valuable for our audience. Would you be open to a brief conversation?",
            "Hi {first_name}, wanted to reconnect and see if this would be of interest. The Industrial Distributors Podcast focuses on conversations with leaders shaping GCC growth, digital transformation, and operational excellence. Happy to share more details or connect at a time convenient for you.\n\nCalendly: https://calendly.com/vserve/gcc-executive-insights-session",
            "Hi {first_name}, I understand your schedule may be busy, so I wanted to make one final follow-up. We would be honored to feature your GCC journey and insights with our executive audience. If this is something you’d consider, please feel free to choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session",
        ],
        'inmail_subject': 'Invitation to Join the GCC Leaders Podcast',
        'inmail': "Hi {first_name},\n\nWe are featuring GCC leaders and transformation experts on the Industrial Distributors Podcast. Given your experience in building and scaling GCC operations, we would love to have you share your insights on GCC growth, digital transformation, operational excellence, and the future of global teams.\n\nAt Vserve, we assist GCC teams with dedicated resources for PDM & catalog mapping, product data standardization, attribute enrichment, taxonomy alignment, and vendor data management. Our specialists work with existing PIM, ERP, and product data systems to streamline processes and improve operational efficiency.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session",
        'inmail_track': [
            {'subject': 'GCC Leaders Podcast Invitation', 'body': "Hi {first_name},\n\nI hope you're doing well.\n\nI wanted to follow up on my invitation to join the Industrial Distributors Podcast, where we are featuring GCC leaders and transformation experts.\n\nGiven your experience in building and scaling GCC operations, we would love to have you share your insights on GCC growth, digital transformation, operational excellence, and the future of global teams.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
            {'subject': 'Sharing GCC Transformation Insights on Our Podcast', 'body': "Just checking in regarding my previous message about the Industrial Distributors Podcast.\n\nWe are bringing together GCC leaders to discuss how organizations are driving transformation, improving operational efficiency, and building high-performing global teams.\n\nYour experience and perspective would be valuable for our audience of industry professionals and decision-makers.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
            {'subject': 'Final Follow-Up: Podcast Invitation', 'body': "Hi {first_name},\n\nI wanted to reach out one last time regarding our invitation to be featured on the Industry Top Leaders Podcast.\n\nWe would be delighted to have you share your journey, experiences, and insights on GCC operations, digital transformation, and scaling global capabilities.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
        ],
    },
    'GCC-Ranganathan': {
            'accounts': [
                {'account': 'Ranganathan A', 'search_url': 'https://www.linkedin.com/sales/search/people?savedSearchId=1993488900', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
            ],
            'invite': "Hi {first_name}, your experience in leading GCC operations caught our attention. We're featuring GCC leaders on the Industry Top Leaders Podcast to discuss transformation, innovation, and scaling global teams. We'd be honored to have you as a guest.",
            'invite_track': [
                "Hi {first_name}, Thanks for connecting!\n\nWe'd be delighted to have you join us on the Industry Top Leaders Podcast and share your insights, experiences, and perspective with our audience. We believe your expertise would make for a valuable conversation. We're inviting executives from different companies to discuss distribution, digital transformation, AI, supply chain innovation, customer experience, and leadership.\n\nYou can choose a convenient date and time through our calendar here: https://calendly.com/vserve/gcc-executive-insights-session\n\nLooking forward to having you on the podcast!",
                "Hi {first_name}, just wanted to follow up on my previous message.\n\nWe'd be happy to have you join us for a conversation and share your insights with our audience.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session",
                "Hi {first_name}, just reaching out one last time regarding the Industry Top Leaders Podcast.\n\nWe'd love to have you join us and hear your perspective on the industry, leadership, and the trends shaping businesses today.\n\nIf you're interested, you can choose a convenient time here: https://calendly.com/vserve/gcc-executive-insights-session\n\nHope to have you on the podcast!",
            ],
            'inmail_subject': 'Invitation to Join the GCC Leaders Podcast',
            'inmail': "Hi {first_name},\n\nI hope you're doing well.\n\nWe are featuring GCC leaders and transformation experts on the Industrial Distributors Podcast. Given your experience in building and scaling GCC operations, we would love to have you share your insights on GCC growth, digital transformation, operational excellence, and the future of global teams.\n\nAt Vserve, we assist GCC teams with dedicated resources for PDM & catalog mapping, product data standardization, attribute enrichment, taxonomy alignment, and vendor data management. Our specialists work with existing PIM, ERP, and product data systems to streamline processes and improve operational efficiency.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session",
            'inmail_track': [
                {'subject': 'GCC Leaders Podcast Invitation', 'body': "Hi {first_name},\n\nI hope you're doing well.\n\nI wanted to follow up on my invitation to join the Industrial Distributors Podcast, where we are featuring GCC leaders and transformation experts.\n\nGiven your experience in building and scaling GCC operations, we would love to have you share your insights on GCC growth, digital transformation, operational excellence, and the future of global teams.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
                {'subject': 'Sharing GCC Transformation Insights on Our Podcast', 'body': "Just checking in regarding my previous message about the Industrial Distributors Podcast.\n\nWe are bringing together GCC leaders to discuss how organizations are driving transformation, improving operational efficiency, and building high-performing global teams.\n\nYour experience and perspective would be valuable for our audience of industry professionals and decision-makers.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
                {'subject': 'Final Follow-Up: Podcast Invitation', 'body': "Hi {first_name},\n\nI wanted to reach out one last time regarding our invitation to be featured on the Industry Top Leaders Podcast.\n\nWe would be delighted to have you share your journey, experiences, and insights on GCC operations, digital transformation, and scaling global capabilities.\n\nWould you be open to joining us for this conversation? Please let us know your availability for a call, or you can choose a convenient time here:\nhttps://calendly.com/vserve/gcc-executive-insights-session"},
            ],
        },
    # 'CXO Podcast': {
    #     'search_url': DEFAULT_SEARCH_URL,
    #     'accounts': [
    #         {'account': 'Anne Davis', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #         {'account': 'Kimberly Morrison', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #         {'account': 'Cynthia David', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #         {'account': 'Andrew Dreger', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #         {'account': 'David Bodiford', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
    #         {'account': 'Cindy Smith', 'invite_limit': DEFAULT_INVITE_LIMIT, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},

    #     ],
    #     'invite': "Hi {first_name}, we're featuring Private Equity leaders on our executive leadership podcast hosted by our CEO Siva Balakrishnan. Your insights on leadership, growth, operational excellence, and business transformation would bring valuable perspectives to our audience.",
    #     'invite_track': [
    #         "Hi {first_name},\n\nWe're featuring Private Equity leaders and investment professionals on our executive leadership podcast, hosted by Vserve CEO Siva Balakrishnan.\n\nWe would value your perspective on leadership, market trends, business growth, operational improvement, and the strategies that help organizations achieve long-term success.\n\nWe're inviting PE leaders to share their insights on:\n\n• Trends shaping today's business landscape\n• Identifying opportunities in evolving markets\n• Driving sustainable growth\n• Improving operational performance\n• Leadership strategies and decision-making\n• Building long-term business value\n\nThis is an opportunity to share your experiences, lessons learned, and perspectives with an audience of executives, entrepreneurs, and business decision-makers.\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, where he shared insights on leadership, operational excellence, scaling teams, and sustainable growth.\n\nPreview: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nThis is not a sales conversation - we would simply like to explore your experience and perspectives as a guest on the podcast.\n\nWould you be open to a brief conversation?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
    #         "Hi {first_name},\n\nI wanted to follow up on my previous message regarding our executive leadership podcast.\n\nWe're inviting a select group of Private Equity professionals and business leaders to share their perspectives on growth, leadership, operational excellence, and the future of business.\n\nWe'd love to discuss your insights on:\n\n• Market trends and emerging opportunities\n• Strategies for sustainable growth\n• Improving business performance\n• Technology and innovation\n• Leadership challenges and opportunities\n• Building organizations for long-term success\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his insights on leadership, operational excellence, and scaling organizations.\n\nYou can watch a short preview here:\nhttps://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
    #         "Hi {first_name},\n\nI wanted to follow up once more regarding our executive leadership podcast.\n\nWe're inviting Private Equity leaders to share their experiences, strategies, and lessons learned around growth, leadership, and navigating change in today's business environment.\n\nWe'd love to discuss your thoughts on:\n\n• Scaling organizations effectively\n• Driving operational improvements\n• Leveraging technology and innovation\n• Building high-performing teams\n• Navigating business challenges and opportunities\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his perspective on leadership, operational excellence, and sustainable growth.\n\nYou can watch a short preview here:\nhttps://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to discuss the format?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
    #     ],
    #     'inmail_subject': 'Invitation to Join Our Executive Leadership Podcast',
    #     'inmail': "Hi {first_name}, we're featuring Private Equity leaders on our executive leadership podcast hosted by our CEO Siva Balakrishnan. Your insights on leadership, growth, operational excellence, and business transformation would bring valuable perspectives to our audience.",
    #     'inmail_track': [
    #         {'subject': 'Invitation to Join Our Executive Leadership Podcast', 'body': "Hi {first_name},\n\nWe're featuring Private Equity leaders and investment professionals on our executive leadership podcast, hosted by Vserve CEO Siva Balakrishnan.\n\nWe would value your perspective on leadership, market trends, business growth, operational improvement, and the strategies that help organizations achieve long-term success.\n\nWe're inviting PE leaders to share their insights on:\n\n• Trends shaping today's business landscape\n• Identifying opportunities in evolving markets\n• Driving sustainable growth\n• Improving operational performance\n• Leadership strategies and decision-making\n• Building long-term business value\n\nThis is an opportunity to share your experiences, lessons learned, and perspectives with an audience of executives, entrepreneurs, and business decision-makers.\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, where he shared insights on leadership, operational excellence, scaling teams, and sustainable growth.\n\nPreview: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nThis is not a sales conversation - we would simply like to explore your experience and perspectives as a guest on the podcast.\n\nWould you be open to a brief conversation?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
    #         {'subject': 'Invitation to Join Our Executive Leadership Podcast', 'body': "Hi {first_name},\n\nI wanted to follow up on my previous message regarding our executive leadership podcast.\n\nWe're inviting a select group of Private Equity professionals and business leaders to share their perspectives on growth, leadership, operational excellence, and the future of business.\n\nWe'd love to discuss your insights on:\n\n• Market trends and emerging opportunities\n• Strategies for sustainable growth\n• Improving business performance\n• Technology and innovation\n• Leadership challenges and opportunities\n• Building organizations for long-term success\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his insights on leadership, operational excellence, and scaling organizations.\n\nYou can watch a short preview here:\nhttps://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
    #         {'subject': 'Invitation to Join Our Executive Leadership Podcast', 'body': "Hi {first_name},\n\nI wanted to follow up once more regarding our executive leadership podcast.\n\nWe're inviting Private Equity leaders to share their experiences, strategies, and lessons learned around growth, leadership, and navigating change in today's business environment.\n\nWe'd love to discuss your thoughts on:\n\n• Scaling organizations effectively\n• Driving operational improvements\n• Leveraging technology and innovation\n• Building high-performing teams\n• Navigating business challenges and opportunities\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his perspective on leadership, operational excellence, and sustainable growth.\n\nYou can watch a short preview here:\nhttps://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to discuss the format?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
    #     ],
    # },
    'CXO - Operating Partner': {
        # Doc gives no saved search for this one - source from the default search.
        'search_url': 'https://www.linkedin.com/sales/search/people?savedSearchId=1993756220',
        'accounts': [
            {'account': 'Andrew Dreger', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
            {'account': 'Cindy Smith', 'invite_limit': 5, 'inmail_limit': DEFAULT_INMAIL_LIMIT, 'message_limit': DEFAULT_MESSAGE_LIMIT},
        ],
        'invite': "Hi {first_name}, we're featuring industrial distribution leaders and Private Equity professionals on the Industrial Distributors Podcast hosted by Vserve CEO Siva Balakrishnan. Your expertise in driving growth, operational excellence, and value creation would bring valuable insights to our audience.",
        'invite_track': [
            "Hi {first_name}, I'd love to connect.\n\nWe're featuring private equity leaders and investment professionals on the Industrial Distributors Podcast, hosted by Vserve CEO Siva Balakrishnan.\n\nGiven your experience investing in manufacturing and industrial distributor companies, your perspective on value creation, portfolio growth, and operational transformation would be highly valuable to our audience.\n\nWe're inviting private equity leaders to share their expertise in areas such as:\n• Industrial distribution and manufacturing investments\n• Identifying high-potential investment opportunities\n• Portfolio company growth strategies\n• Operational improvement and value creation initiatives\n• M&A strategy and integration\n• Scaling businesses and driving long-term enterprise value\n\nBy participating, you'll have the opportunity to showcase your investment expertise, share your approach to building value in industrial companies, highlight your firm's experience in the sector, and contribute insights that can help shape the future of industrial distribution.\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, on the Industrial Distributors Podcast. Jason shared his insights on the industrial distribution landscape, operational excellence, scaling operations, and creating sustainable value within industrial businesses.\n\nYou can watch a short preview of the conversation here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nThis is not a sales conversation - it's an opportunity to share your investment journey, lessons learned, and perspectives on driving growth and transformation across industrial portfolio companies with an audience of industry executives and decision-makers.\n\nWould you be open to a brief conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
            "Hi {first_name},\n\nI wanted to follow up on my previous message regarding the Industrial Distributors Podcast.\n\nWe're inviting a select group of Private Equity professionals who invest in manufacturing and industrial distributor companies to share their perspectives on value creation, portfolio growth, and operational transformation.\n\nWe'd love to discuss your insights on:\n• Identifying opportunities in industrial markets\n• Driving growth across portfolio companies\n• Improving operational performance\n• Creating long-term enterprise value\n• Navigating M&A and industry transformation\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his insights on operational excellence and the evolving industrial distribution landscape.\n\nYou can watch a short preview here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
            "Hi {first_name},\n\nI wanted to follow up on my previous message regarding the Industrial Distributors Podcast.\n\nWe're inviting a select group of industrial distribution leaders to share their experiences, strategies, and lessons learned on driving growth and operational excellence in the industry.\n\nWe'd love to discuss your insights on:\n• Scaling distribution operations\n• Building stronger customer relationships\n• Improving sales and operational performance\n• Leveraging technology and digital transformation\n• Navigating challenges and opportunities in industrial markets\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his perspective on operational excellence and the evolving industrial distribution landscape.\n\nYou can watch a short preview here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to discuss the format?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09",
        ],
        'inmail_subject': "{first_name}, We'd Love to Feature You on the Industrial Distributors Podcast",
        'inmail': "Hi {first_name}, we're featuring industrial distribution leaders and Private Equity professionals on the Industrial Distributors Podcast hosted by Vserve CEO Siva Balakrishnan. Your expertise in driving growth, operational excellence, and value creation would bring valuable insights to our audience.",
        'inmail_track': [
            {'subject': 'Invitation to Join the Industrial Distributors Podcast', 'body': "Hi {first_name}, I'd love to connect.\n\nWe're featuring private equity leaders and investment professionals on the Industrial Distributors Podcast, hosted by Vserve CEO Siva Balakrishnan.\n\nGiven your experience investing in manufacturing and industrial distributor companies, your perspective on value creation, portfolio growth, and operational transformation would be highly valuable to our audience.\n\nWe're inviting private equity leaders to share their expertise in areas such as:\n• Industrial distribution and manufacturing investments\n• Identifying high-potential investment opportunities\n• Portfolio company growth strategies\n• Operational improvement and value creation initiatives\n• M&A strategy and integration\n• Scaling businesses and driving long-term enterprise value\n\nBy participating, you'll have the opportunity to showcase your investment expertise, share your approach to building value in industrial companies, highlight your firm's experience in the sector, and contribute insights that can help shape the future of industrial distribution.\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, on the Industrial Distributors Podcast. Jason shared his insights on the industrial distribution landscape, operational excellence, scaling operations, and creating sustainable value within industrial businesses.\n\nYou can watch a short preview of the conversation here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nThis is not a sales conversation - it's an opportunity to share your investment journey, lessons learned, and perspectives on driving growth and transformation across industrial portfolio companies with an audience of industry executives and decision-makers.\n\nWould you be open to a brief conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
            {'subject': 'Share Your Industrial Growth Story with Our Audience', 'body': "Hi {first_name},\n\nI wanted to follow up on my previous message regarding the Industrial Distributors Podcast.\n\nWe're inviting a select group of Private Equity professionals who invest in manufacturing and industrial distributor companies to share their perspectives on value creation, portfolio growth, and operational transformation.\n\nWe'd love to discuss your insights on:\n• Identifying opportunities in industrial markets\n• Driving growth across portfolio companies\n• Improving operational performance\n• Creating long-term enterprise value\n• Navigating M&A and industry transformation\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his insights on operational excellence and the evolving industrial distribution landscape.\n\nYou can watch a short preview here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to explore being a guest?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
            {'subject': 'Featuring Leaders Driving Growth in Industrial Distribution', 'body': "Hi {first_name},\n\nI wanted to follow up on my previous message regarding the Industrial Distributors Podcast.\n\nWe're inviting a select group of industrial distribution leaders to share their experiences, strategies, and lessons learned on driving growth and operational excellence in the industry.\n\nWe'd love to discuss your insights on:\n• Scaling distribution operations\n• Building stronger customer relationships\n• Improving sales and operational performance\n• Leveraging technology and digital transformation\n• Navigating challenges and opportunities in industrial markets\n\nWe recently featured Jason Dierks, Executive Vice President of Operations at Berkshire Tool Supply Group, who shared his perspective on operational excellence and the evolving industrial distribution landscape.\n\nYou can watch a short preview here: https://www.youtube.com/watch?v=HHo9GqlJYy8\n\nWould you be open to a brief 15-minute conversation to discuss the format?\n👉 https://calendly.com/vserve/new-meeting?month=2025-09"},
        ],
    },
}


def get_campaign(campaign_id):
    """Return the campaign dict for `campaign_id` (a value from the sheet's
    'Campaigns' column). Raises clearly instead of failing on a KeyError deep
    inside a message-formatting call."""
    # Web-app overrides win when present (updated limits/copy take effect on the
    # next run without touching this file). Falls back to the built-in registry.
    overrides = load_overrides()
    if campaign_id in overrides:
        merged = _deep_merge(dict(CAMPAIGNS[campaign_id]), overrides[campaign_id])
        return merged
    if campaign_id not in CAMPAIGNS:
        raise KeyError(f"No campaign defined for '{campaign_id}' in campaigns.py")
    return CAMPAIGNS[campaign_id]


def get_account_config(campaign, account):
    """Return the {account, invite_limit, inmail_limit, message_limit,
    calendar_url, ...} dict for `account` within `campaign['accounts']`. This is
    how a campaign shared by multiple accounts (e.g. SCM Podcast) gives each one
    its own calendar_url and budget without needing separate campaign entries."""
    for acc_cfg in campaign['accounts']:
        if acc_cfg['account'] == account:
            return acc_cfg
    raise KeyError(f"Account '{account}' is not listed under this campaign's 'accounts'")


def campaigns_for_account(account):
    """Return all campaign_ids that a given physical LinkedIn account participates
    in (it may be one of several accounts running that campaign). Useful if you
    ever need to reason about an account's combined activity across all the
    campaigns it touches (e.g. platform-level LinkedIn account safety limits)."""
    return [cid for cid, c in effective_campaigns().items() if any(a['account'] == account for a in c['accounts'])]


# ============================================================
# Web-app overrides: the Outreach Command Center writes edits
# (limits, accounts, message copy) to campaign_overrides.json.
# Overrides are merged on read, so script runs pick up web edits
# without a code deploy. Deleting the file reverts to built-ins.
# ============================================================
import json as _json
import os as _os

OVERRIDE_FILE = _os.environ.get('CAMPAIGN_OVERRIDES_FILE', './campaign_overrides.json')


def load_overrides():
    """Return {campaign_id: partial_campaign_dict} from the overrides file, or {}.
    Never raises - a malformed file is reported and ignored (built-ins win)."""
    if not _os.path.exists(OVERRIDE_FILE):
        return {}
    try:
        with open(OVERRIDE_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ Ignoring malformed {OVERRIDE_FILE}: {e}")
        return {}


def save_overrides(overrides):
    """Persist the full overrides dict (called by the web app's campaign editor)."""
    with open(OVERRIDE_FILE, 'w', encoding='utf-8') as f:
        _json.dump(overrides, f, indent=2, ensure_ascii=False)


def _deep_merge(base, override):
    """Recursively merge `override` into `base` (dicts merge, everything else is
    replaced). Returns a new dict; neither input is mutated."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def effective_campaigns():
    """The campaign registry the pipeline should act on: built-in CAMPAIGNS with
    any web-app overrides merged in. Use this instead of CAMPAIGNS wherever the
    pipeline reads campaign config."""
    overrides = load_overrides()
    if not overrides:
        return CAMPAIGNS
    merged = {}
    for cid, campaign in CAMPAIGNS.items():
        merged[cid] = _deep_merge(campaign, overrides.get(cid, {}))
    return merged