# accounts/models.py - APPROVAL PERMISSIONS
"""
User Model Extensions - Tasdiqlash huquqlari

VERSIYA: 8.0 - APPROVAL SYSTEM
===============================

YANGI FIELDLAR:
1. can_approve_transactions - Tranzaksiyalarni tasdiqlash
2. can_approve_expenses - Xarajatlarni tasdiqlash
3. can_approve_commissions - Komissiyalarni tasdiqlash
4. can_approve_consignment - Konsignatsiya to'lovlarini tasdiqlash
5. approval_limit - Maksimal tasdiqlash summasi ($0 = cheksiz)
6. assigned_stores - Qaysi do'konlar uchun tasdiqlashi mumkin

QOIDALAR:
- Owner: barcha huquqlar (default)
- Seller: hech qanday huquq yo'q (default)
- Manager: owner bergan huquqlar

DELEGATION:
- Owner sotuvchiga huquq beradi
- Sotuvchi faqat o'z do'konini tasdiqlaydi
- Owner barcha do'konlarni tasdiqlaydi
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from decimal import Decimal


class Store(models.Model):
    """Do'kon modeli"""
    name = models.CharField(max_length=100)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stores'
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    User modeli - Approval permissions bilan

    ROLE HIERARCHY:
    ===============
    1. Owner (Superuser)
       - Barcha huquqlar
       - Barcha do'konlar
       - Cheksiz approval limit
       - Boshqalarga huquq berishi mumkin

    2. Manager
       - Owner bergan huquqlar
       - Tayinlangan do'konlar
       - Belgilangan approval limit
       - Boshqalarga huquq bera olmaydi

    3. Seller
       - Faqat sotish huquqi
       - Faqat o'z do'koni
       - Tasdiqlash huquqi yo'q (default)
       - Owner bergan bo'lsa, faqat o'z do'konini tasdiqlaydi
    """

    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('manager', 'Manager'),
        ('seller', 'Seller'),
    ]

    # Asosiy ma'lumotlar
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='seller')
    store = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )
    phone = models.CharField(max_length=20, blank=True)

    # === APPROVAL PERMISSIONS ===

    # 1. TRANSACTION APPROVAL (Tranzaksiyalar)
    can_approve_transactions = models.BooleanField(
        default=False,
        help_text="Sotuvlarni va boshqa tranzaksiyalarni tasdiqlash huquqi"
    )

    # 2. EXPENSE APPROVAL (Xarajatlar)
    can_approve_expenses = models.BooleanField(
        default=False,
        help_text="Xarajatlarni tasdiqlash huquqi"
    )

    # 3. COMMISSION APPROVAL (Komissiyalar)
    can_approve_commissions = models.BooleanField(
        default=False,
        help_text="Komissiyalarni tasdiqlash va to'lash huquqi"
    )

    # 4. CONSIGNMENT APPROVAL (Konsignatsiya)
    can_approve_consignment = models.BooleanField(
        default=False,
        help_text="Konsignatsiya to'lovlarini tasdiqlash huquqi"
    )

    # 5. APPROVAL LIMIT (Maksimal summa)
    approval_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Maksimal tasdiqlash summasi. 0 = cheksiz (faqat owner uchun)"
    )

    # 6. ASSIGNED STORES (Tayinlangan do'konlar)
    assigned_stores = models.ManyToManyField(
        Store,
        blank=True,
        related_name='approvers',
        help_text="Qaysi do'konlar uchun tasdiqlash huquqi bor"
    )

    # === DELEGATION TRACKING ===

    # Kim tomonidan huquq berilgan
    delegated_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delegated_users',
        help_text="Huquqni bergan shaxs"
    )

    # Qachon huquq berilgan
    delegated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Huquq berilgan sana"
    )

    # Huquq berilish sababi
    delegation_note = models.TextField(
        blank=True,
        help_text="Nima uchun huquq berilgani haqida izoh"
    )

    # === METADATA ===

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    must_change_password = models.BooleanField(
        default=False,
        help_text="Keyingi kirishda parolni o'zgartirishi shart"
    )

    password_changed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Oxirgi parol o'zgartirish sanasi"
    )

    class Meta:
        db_table = 'users'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    # ============================================
    # PERMISSION CHECK METHODS
    # ============================================

    def is_owner(self) -> bool:
        """Owner/Superuser ekanligini tekshirish"""
        return self.is_superuser or self.role == 'owner'

    def can_approve_amount(self, amount: Decimal) -> bool:
        """
        Berilgan summani tasdiqlash huquqi bormi?

        Args:
            amount: Summa

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        if self.is_owner():
            return True  # Owner cheksiz

        if self.approval_limit == Decimal('0.00'):
            return False  # 0 = huquq yo'q

        return amount <= self.approval_limit

    def can_approve_for_store(self, store) -> bool:
        """
        Berilgan do'kon uchun tasdiqlash huquqi bormi?

        Args:
            store: Store object yoki store_id

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        if self.is_owner():
            return True  # Owner barcha do'konlar

        # Store object -> id
        store_id = store.id if hasattr(store, 'id') else store

        # Assigned stores ichida bormi?
        return self.assigned_stores.filter(id=store_id).exists()

    def can_approve_transaction(self, transaction) -> bool:
        """
        Tranzaksiyani tasdiqlash huquqi bormi?

        Args:
            transaction: Transaction object

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        # Permission check
        if not self.can_approve_transactions:
            return False

        # Store check
        if not self.can_approve_for_store(transaction.store_id):
            return False

        # Amount check
        if not self.can_approve_amount(transaction.amount):
            return False

        return True

    def can_approve_expense(self, expense) -> bool:
        """
        Xarajatni tasdiqlash huquqi bormi?

        Args:
            expense: Transaction object (type='expense')

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        # Permission check
        if not self.can_approve_expenses:
            return False

        # Store check
        if not self.can_approve_for_store(expense.store_id):
            return False

        # Amount check
        if not self.can_approve_amount(expense.amount):
            return False

        return True

    def can_approve_commission_obj(self, commission) -> bool:
        """
        Komissiyani tasdiqlash huquqi bormi?

        Args:
            commission: SellerCommission object

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        # Permission check
        if not self.can_approve_commissions:
            return False

        # Store check
        tx = commission.transaction
        if not self.can_approve_for_store(tx.store_id):
            return False

        # Amount check
        amount = abs(commission.amount)  # Manfiy bo'lishi mumkin
        if not self.can_approve_amount(amount):
            return False

        return True

    def can_approve_consignment_due(self, due) -> bool:
        """
        Konsignatsiya qarzini tasdiqlash huquqi bormi?

        Args:
            due: ConsignmentDue object

        Returns:
            bool: Tasdiqlash mumkinmi?
        """
        # Permission check
        if not self.can_approve_consignment:
            return False

        # Store check
        if not self.can_approve_for_store(due.store_id):
            return False

        # Amount check
        if not self.can_approve_amount(due.base_amount):
            return False

        return True

    # ============================================
    # DELEGATION METHODS
    # ============================================

    def delegate_approval_to(
            self,
            user,
            permissions: dict,
            stores: list = None,
            limit: Decimal = None,
            note: str = ""
    ):
        """
        Boshqa foydalanuvchiga tasdiqlash huquqini berish

        FAQAT OWNER CHAQIRA OLADI!

        Args:
            user: User object (huquq beriladigan shaxs)
            permissions: dict - {
                'transactions': bool,
                'expenses': bool,
                'commissions': bool,
                'consignment': bool,
            }
            stores: list[Store] - Tayinlangan do'konlar (None = barcha)
            limit: Decimal - Maksimal summa (None = cheksiz)
            note: str - Izoh

        Raises:
            PermissionError: Agar owner bo'lmasa

        Example:
            owner.delegate_approval_to(
                user=seller,
                permissions={
                    'transactions': True,
                    'expenses': True,
                    'commissions': False,
                    'consignment': False,
                },
                stores=[store1, store2],
                limit=Decimal('1000.00'),
                note="Ishonchli sotuvchi"
            )
        """
        from django.utils import timezone

        # Faqat owner
        if not self.is_owner():
            raise PermissionError("Faqat owner huquq berishi mumkin!")

        # Permissions
        user.can_approve_transactions = permissions.get('transactions', False)
        user.can_approve_expenses = permissions.get('expenses', False)
        user.can_approve_commissions = permissions.get('commissions', False)
        user.can_approve_consignment = permissions.get('consignment', False)

        # Limit
        if limit is not None:
            user.approval_limit = limit
        else:
            user.approval_limit = Decimal('0.00')  # Cheksiz (faqat owner)

        # Delegation tracking
        user.delegated_by = self
        user.delegated_at = timezone.now()
        user.delegation_note = note

        # Save
        user.save()

        # Assigned stores
        if stores:
            user.assigned_stores.set(stores)
        else:
            # Barcha aktiv do'konlar
            user.assigned_stores.set(Store.objects.filter(is_active=True))

    def revoke_approval(self):
        """
        Tasdiqlash huquqlarini olib qo'yish

        Owner o'zi chaqirishi mumkin yoki boshqa owner
        """
        self.can_approve_transactions = False
        self.can_approve_expenses = False
        self.can_approve_commissions = False
        self.can_approve_consignment = False
        self.approval_limit = Decimal('0.00')
        self.assigned_stores.clear()

        # Delegation tracking clear
        self.delegated_by = None
        self.delegated_at = None
        self.delegation_note = ""

        self.save()

    def get_approval_summary(self) -> dict:
        """
        Tasdiqlash huquqlari summary

        Returns:
            dict: {
                'is_owner': bool,
                'can_approve': bool,
                'permissions': {...},
                'limit': Decimal,
                'stores': list[Store],
                'delegated_by': User or None,
            }
        """
        can_approve_any = (
                self.can_approve_transactions or
                self.can_approve_expenses or
                self.can_approve_commissions or
                self.can_approve_consignment
        )

        return {
            'is_owner': self.is_owner(),
            'can_approve': can_approve_any or self.is_owner(),
            'permissions': {
                'transactions': self.can_approve_transactions,
                'expenses': self.can_approve_expenses,
                'commissions': self.can_approve_commissions,
                'consignment': self.can_approve_consignment,
            },
            'limit': self.approval_limit,
            'limit_display': (
                "Cheksiz" if self.approval_limit == Decimal('0.00')
                else f"${self.approval_limit:,.2f}"
            ),
            'stores': list(self.assigned_stores.all()),
            'store_count': self.assigned_stores.count(),
            'delegated_by': self.delegated_by,
            'delegated_at': self.delegated_at,
        }


# ============================================
# HELPER FUNCTIONS
# ============================================

def is_owner(user) -> bool:
    """User owner/superuser ekanligini tekshirish"""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or getattr(user, 'role', '') == 'owner'


def can_user_approve(user, obj, approval_type: str) -> bool:
    """
    Foydalanuvchi berilgan obyektni tasdiqlashi mumkinmi?

    Args:
        user: User object
        obj: Transaction/Commission/ConsignmentDue object
        approval_type: 'transaction' | 'expense' | 'commission' | 'consignment'

    Returns:
        bool: Tasdiqlash mumkinmi?
    """
    if not user or not user.is_authenticated:
        return False

    # Owner - barcha huquqlar
    if is_owner(user):
        return True

    # Type'ga qarab
    if approval_type == 'transaction':
        return user.can_approve_transaction(obj)
    elif approval_type == 'expense':
        return user.can_approve_expense(obj)
    elif approval_type == 'commission':
        return user.can_approve_commission_obj(obj)
    elif approval_type == 'consignment':
        return user.can_approve_consignment_due(obj)

    return False


# ============================================
# SIGNAL: AUTO-ASSIGN OWNER PERMISSIONS
# ============================================

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User, dispatch_uid="user_auto_permissions_v8")
def auto_assign_owner_permissions(sender, instance, created, **kwargs):
    """
    Yangi owner yaratilganda avtomatik barcha huquqlarni berish

    QOIDALAR:
    - Owner: barcha huquqlar
    - Seller: hech narsa (manual)
    """
    if created and instance.is_owner():
        # Barcha huquqlar
        User.objects.filter(pk=instance.pk).update(
            can_approve_transactions=True,
            can_approve_expenses=True,
            can_approve_commissions=True,
            can_approve_consignment=True,
            approval_limit=Decimal('0.00'),  # Cheksiz
        )

        # Barcha do'konlar
        instance.assigned_stores.set(Store.objects.filter(is_active=True))


# ============================================
# NOTES
# ============================================

"""
MIGRATION SCRIPT:
=================

# 1. Create migration
python manage.py makemigrations accounts

# 2. Migrate
python manage.py migrate accounts

# 3. Assign permissions to existing owners
python manage.py shell

>>> from accounts.models import User
>>> owners = User.objects.filter(is_superuser=True)
>>> for owner in owners:
...     owner.can_approve_transactions = True
...     owner.can_approve_expenses = True
...     owner.can_approve_commissions = True
...     owner.can_approve_consignment = True
...     owner.approval_limit = 0
...     owner.save()
...     owner.assigned_stores.set(Store.objects.all())

DELEGATION EXAMPLE:
===================

# Owner sotuvchiga huquq berish
owner = User.objects.get(username='owner')
seller = User.objects.get(username='seller1')

owner.delegate_approval_to(
    user=seller,
    permissions={
        'transactions': True,
        'expenses': True,
        'commissions': False,
        'consignment': False,
    },
    stores=[store1, store2],
    limit=Decimal('500.00'),
    note="Ishonchli sotuvchi, kichik summalarga ruxsat"
)

# Huquqni olib qo'yish
seller.revoke_approval()

# Summary ko'rish
summary = seller.get_approval_summary()
print(summary)
"""