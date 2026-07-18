from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('banklist', '0003_uploadedstatement_transaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceiptDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('drive_file_id', models.CharField(max_length=255)),
                ('file_name', models.CharField(max_length=255)),
                ('file_link', models.URLField(blank=True, max_length=500, null=True)),
                ('mime_type', models.CharField(blank=True, max_length=150)),
                ('extracted', models.BooleanField(default=False)),
                ('extraction_error', models.TextField(blank=True)),
                ('receipt_no', models.CharField(blank=True, max_length=120)),
                ('receipt_date', models.DateField(blank=True, null=True)),
                ('amount', models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True)),
                ('uploaded_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='receipts', to='banklist.company')),
            ],
            options={
                'db_table': 'receipt_documents',
                'ordering': ['-uploaded_at', '-created_at'],
                'unique_together': {('company', 'drive_file_id')},
            },
        ),
        migrations.AddIndex(
            model_name='receiptdocument',
            index=models.Index(fields=['company', 'extracted'], name='receipt_doc_company_8f6d16_idx'),
        ),
        migrations.AddIndex(
            model_name='receiptdocument',
            index=models.Index(fields=['receipt_date'], name='receipt_doc_receipt_1fcb9f_idx'),
        ),
    ]
